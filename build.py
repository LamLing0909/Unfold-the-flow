"""Build the file:// demo from its source files; no third-party packages needed."""
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STYLE_SLOT = '<!-- BUILD:STYLE -->'
PYTHON_SLOT = '<!-- BUILD:PYTHON -->'
IMPORT_LINE = 'from diagram import Diagram\n'


def build_html():
    """Combine template, CSS and Python sources into the standalone HTML."""
    template = (ROOT / 'index.template.html').read_text(encoding='utf-8')
    css = (ROOT / 'style.css').read_text(encoding='utf-8')
    module = (ROOT / 'diagram.py').read_text(encoding='utf-8')
    app = (ROOT / 'app.py').read_text(encoding='utf-8')
    if template.count(STYLE_SLOT) != 1 or template.count(PYTHON_SLOT) != 1:
        raise ValueError('Template must contain each build placeholder exactly once.')
    if app.count(IMPORT_LINE) != 1:
        raise ValueError('app.py must contain exactly one diagram import.')
    # Both Python files share a script scope in the standalone page. Diagram
    # has already been defined there, so importing it from a file is unnecessary.
    app_inline = app.replace(IMPORT_LINE, '', 1)
    python_source = '\n' + module + '\n\n' + app_inline + '\n'
    # A closing HTML tag would terminate the enclosing element, even if it
    # appears inside a Python or CSS string. Fail explicitly instead of
    # silently producing a broken or unsafe file.
    if '</script' in python_source.lower() or '</style' in css.lower():
        raise ValueError('Embedded source contains an HTML closing tag.')
    return template.replace(STYLE_SLOT, css).replace(PYTHON_SLOT, python_source)


def main():
    parser = argparse.ArgumentParser(description='Build the standalone Unfold the flow page.')
    parser.add_argument('--check', action='store_true', help='Check whether index.html is up to date.')
    args = parser.parse_args()
    output = ROOT / 'index.html'
    result = build_html()
    if args.check:
        if not output.exists() or output.read_text(encoding='utf-8') != result:
            parser.exit(1, 'index.html is out of date; run python build.py\n')
        print('index.html is up to date.')
    else:
        output.write_text(result, encoding='utf-8')
        print('Built index.html.')


if __name__ == '__main__':
    main()
