"""Capture the README screenshot from the actual app with an isolated synthetic demo."""
import argparse
from pathlib import Path
import tempfile
import threading

from playwright.sync_api import sync_playwright, expect
from budget_server import BudgetHTTPServer, Handler, Store
from demo import create_demo


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path(__file__).parent / 'docs' / 'images')
    args = parser.parse_args(); args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as parent:
        folder = Path(parent) / 'demo'; create_demo(folder)
        server = BudgetHTTPServer(('127.0.0.1', 0), Handler)
        server.store, server.token, server.previews = Store(folder), 'synthetic-demo-token', {}
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(viewport={'width': 1440, 'height': 1080}, color_scheme='light')
                page = context.new_page(); errors = []
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.goto(f'http://127.0.0.1:{server.server_port}/')
                expect(page).to_have_title('net-month')
                expect(page.locator('.bm-brand')).to_have_text('net-month')
                expect(page.locator('#save-status')).to_have_text('Saved locally')
                page.locator('#month-select').select_option('2026-10')
                expect(page.locator('.bm-category')).to_have_text([f'Category {i}' for i in range(1, 8)])
                expect(page.locator('.bm-value')).to_have_text(['$2,000.00', '$1,600.00', '$400.00'])
                expect(page.locator('.bm-total td')).to_have_text(
                    ['Total', '$2,000.00', '$1,800.00', '$200.00', '$1,600.00', '-$400.00'])
                page.screenshot(path=str(args.output / 'monthly.png'), full_page=True)
                assert not errors, errors
                context.close(); browser.close()
        finally:
            server.shutdown(); server.server_close(); thread.join()
    print('Captured the verified monthly screenshot from synthetic records.')


if __name__ == '__main__':
    main()
