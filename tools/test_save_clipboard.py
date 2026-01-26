import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tv_downloader_enhanced import EnhancedTVScraper
from pathlib import Path

s=EnhancedTVScraper()
# Read the known-correct clipboard dump
correct = Path('pinescript_downloads/Volume_Profile_correct_from_copy_clicpboard.pine').read_text(encoding='utf-8')
result={
    'title':'Volume Profile - Density of Density [DAFE]',
    'script_id':'8jW3AO3z',
    'author':'DskyzInvestments',
    'url':'https://www.tradingview.com/script/8jW3AO3z-Volume-Profile-Density-of-Density-DAFE/',
    'published_date':'',
    'version':'',
    'is_strategy':False,
    'boosts':0,
    'tags':['multitimeframe','Support and Resistance','Volume Profile'],
    'source_origin':'clipboard',
    'source_raw':correct
}

p = s.save_script(result, '8jW3AO3z')
print('wrote file:',p)
