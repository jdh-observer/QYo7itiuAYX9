"""Build the text-free derivative of the Der Spiegel corpus used in article.ipynb.

Reads the full-text CSV files in corpus_data/csv_daten, which are not part of
this repository, and writes the files the notebook loads in their place:
corpus_data/metadata/<year>.csv, script/chunking_demo.json, and the exports in
script/ with chunk texts replaced by SHA-1 checksums.

Run from the repository root: python script/build_text_free_corpus.py
"""

import glob
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

FULL_TEXT_DIR = Path('corpus_data/csv_daten')
METADATA_DIR = Path('corpus_data/metadata')
YEARS = range(1950, 1980)

# The same keyword list as in Section 2.5 of the notebook
KEYWORDS = [
    'Computer', 'Elektronenhirn', 'Rechner', 'IBM',
    'Datenverarbeitung', 'EDV', 'Automation', 'Automatisierung',
    'Kybernetik', 'Rechenmaschine', 'Elektronenrechner'
]
PATTERN = '|'.join(KEYWORDS)


def build_metadata_files():
    """Write one text-free CSV file per year and return the full-text corpus."""
    METADATA_DIR.mkdir(parents=True, exist_ok=True)
    dfs = []
    for year in YEARS:
        df_year = pd.read_csv(FULL_TEXT_DIR / f'{year}.csv')
        dfs.append(df_year)
        text = df_year['Text']
        derived = df_year.drop(columns=['Text']).copy()
        derived.insert(df_year.columns.get_loc('Text'), 'has_text', text.notna())
        derived['word_count'] = text.fillna('').str.split().str.len()
        derived['char_count'] = text.fillna('').str.len()
        derived['text_has_keyword'] = text.str.contains(PATTERN, case=False, na=False)
        for keyword in KEYWORDS:
            derived[f'text_has_{keyword}'] = text.str.contains(keyword, case=False, na=False)
        derived.to_csv(METADATA_DIR / f'{year}.csv', index=False)
        print(f'{year}: {len(derived):,} articles')
    return pd.concat(dfs, ignore_index=True)


# Chunking configurations, copied from Section 3.2 of the notebook
from langchain_text_splitters import RecursiveCharacterTextSplitter

# Define our three chunking configurations as offered in SPIEGELragged
chunking_configs = {
    'large': {'chunk_size': 3000, 'chunk_overlap': 300},
    'medium': {'chunk_size': 2000, 'chunk_overlap': 200},
    'small': {'chunk_size': 500, 'chunk_overlap': 50}
}

# Sentence boundary regex for German text: splits at sentence-ending punctuation
# followed by a new sentence, while avoiding false splits at abbreviations
# (e.g. "Dr.", "z.B.", "Mio. DM") by requiring at least two preceding lowercase chars
german_sentence_boundary = (
    r"(?<=[A-Z\u00d6\u00dc\u00c4a-z\u00e4\u00f6\u00fc\u00df]"
    r"[a-z\u00e4\u00f6\u00fc\u00df][.!?])\s+"
    r"(?=[A-Z\u00d6\u00c4\u00dc][a-z\u00e4\u00f6\u00fc\u00df])"
    r"|"
    r"(?<=[a-z][.!?]\u00ab)\s+"
    r"(?=[A-Z\u00d6\u00c4\u00dc][a-z\u00e4\u00f6\u00fc\u00df])"
)

# Create splitters for each configuration
splitters = {}
for name, config in chunking_configs.items():
    splitters[name] = RecursiveCharacterTextSplitter(
        chunk_size=config['chunk_size'],
        chunk_overlap=config['chunk_overlap'],
        is_separator_regex=True,
        separators=[
            r"\n\n",                   # Paragraph breaks
            r"\n",                      # Line breaks
            german_sentence_boundary,    # Sentence boundaries (abbreviation-aware)
            r"\s",                      # Whitespace
            r""                          # Fallback: character-level
        ]
    )


def prepare_documents(df, splitter, max_articles=50):
    """Convert dataframe articles to LangChain Documents with metadata (Section 3.4)."""
    documents = []
    for idx, row in df.head(max_articles).iterrows():
        text = str(row['Text'])
        if not text or text == 'nan':
            continue
        chunks = splitter.split_text(text)
        for i, chunk in enumerate(chunks):
            doc = Document(
                page_content=chunk,
                metadata={
                    'Artikeltitel': row['Artikeltitel'],
                    'Datum': str(row['Datum']),
                    'Year': int(row['Year']),
                    'Ausgabe': int(row['Ausgabe']),
                    'URL': row['URL'],
                    'chunk_index': i,
                    'total_chunks': len(chunks),
                    'has_computerisation': bool(row.get('has_computerisation', False))
                }
            )
            documents.append(doc)
    return documents


def build_chunking_demo(df):
    """Repeat the notebook's steps up to Section 3.4 on the full text."""
    df = df.copy()
    df['Datum'] = pd.to_datetime(df['Datum'], errors='coerce')
    df['Year'] = df['Jahrgang']
    df['char_count'] = df['Text'].fillna('').str.len()
    df['has_computerisation'] = (
        df['Artikeltitel'].str.contains(PATTERN, case=False, na=False) |
        df['Untertitel'].str.contains(PATTERN, case=False, na=False) |
        df['Schlagworte'].str.contains(PATTERN, case=False, na=False) |
        df['Text'].str.contains(PATTERN, case=False, na=False)
    )

    # Demonstration subcorpus, selected as in Section 2.6
    specific_issues_selection = {1964: 14, 1978: 16}
    selected_dfs = [df[(df['Year'] == year) & (df['Ausgabe'] == issue)].copy()
                    for year, issue in specific_issues_selection.items()]
    np.random.seed(42)
    for year in range(1950, 1980):
        if year not in specific_issues_selection:
            year_df = df[df['Year'] == year]
            available_issues = year_df['Ausgabe'].unique()
            if len(available_issues) > 0:
                selected_issue = np.random.choice(available_issues, 1)[0]
                selected_dfs.append(year_df[year_df['Ausgabe'] == selected_issue].copy())
    subcorpus = pd.concat(selected_dfs, ignore_index=True)
    subcorpus['Text'] = subcorpus['Text'].fillna('')

    # Chunking example (Section 3.2)
    candidates = subcorpus[(subcorpus['has_computerisation'] == True) &
                           (subcorpus['char_count'] > 5000)]
    sample_article = candidates.iloc[0]
    sample_text = sample_article['Text']
    chunking = {}
    for name, splitter in splitters.items():
        chunks = splitter.split_text(sample_text)
        chunking[name] = {
            'n_chunks': len(chunks),
            'avg_len': sum(len(c) for c in chunks) / len(chunks),
            'second_chunk_preview': chunks[1][:100],
        }

    # Document preparation example (Section 3.4)
    docs = prepare_documents(subcorpus, splitters['medium'], max_articles=50)

    demo = {
        'sample_article': {
            'url': sample_article['URL'],
            'title': sample_article['Artikeltitel'],
            'char_count': int(len(sample_text)),
            'chunking': chunking,
        },
        'document_preparation': {
            'n_articles': 50,
            'n_documents': len(docs),
            'first_metadata': docs[0].metadata,
        },
    }
    with open('script/chunking_demo.json', 'w', encoding='utf-8') as f:
        json.dump(demo, f, ensure_ascii=False, indent=2)


def strip_text_from_exports():
    """Replace chunk texts in the retrieval and evaluation exports."""
    for path in sorted(glob.glob('script/**/*.csv', recursive=True)):
        export = pd.read_csv(path)
        if 'content' not in export.columns:
            continue
        position = export.columns.get_loc('content')
        checksums = export['content'].map(lambda text: hashlib.sha1(text.encode('utf-8')).hexdigest())
        export = export.drop(columns=['content'])
        export.insert(position, 'content_sha1', checksums)
        export.to_csv(path, index=False)
        print(f'{path}: chunk text replaced by checksum')

    path = Path('script/chunk_analysis.json')
    with open(path, encoding='utf-8') as f:
        analysis = json.load(f)
    if any('chunks' in data for data in analysis.values()):
        for data in analysis.values():
            top_indices = np.argsort(np.array(data['similarities']))[-3:][::-1]
            data['top_previews'] = {str(int(i)): data['chunks'][int(i)][:120] for i in top_indices}
            del data['chunks']
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(analysis, f, ensure_ascii=False)
        print(f'{path}: chunks replaced by previews')


if __name__ == '__main__':
    corpus = build_metadata_files()
    build_chunking_demo(corpus)
    strip_text_from_exports()
