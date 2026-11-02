"""Capture README images from the actual app with an isolated synthetic demo."""
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
                expect(page.locator('#save-status')).to_have_text('Saved locally')
                page.locator('#month-select').select_option('2026-10')
                expect(page.locator('#main-content')).to_contain_text('$2,568.00')
                page.screenshot(path=str(args.output / 'monthly.png'), full_page=True)
                page.get_by_role('tab', name='Transactions', exact=True).click()
                page.locator('#search').fill('Annual insurance')
                page.set_viewport_size({'width': 1440, 'height': 1650})
                annual_id = next(t['id'] for t in server.store.load()['transactions'] if t['description'] == 'Annual insurance')
                page.locator(f'tr[data-id="{annual_id}"]').get_by_role('button', name='Edit', exact=True).click()
                expect(page.locator('[data-field=month]')).to_have_count(12)
                page.locator('#editor').screenshot(path=str(args.output / 'annual-allocation.png'))
                page.keyboard.press('Escape')
                page.set_viewport_size({'width': 1440, 'height': 1080})
                page.locator('#search').fill('Dinner repayment')
                repayment_id = next(t['id'] for t in server.store.load()['transactions'] if t['description'] == 'Dinner repayment')
                page.locator(f'tr[data-id="{repayment_id}"]').get_by_role('button', name='Link credit', exact=True).click()
                expect(page.locator('#editor')).to_contain_text('Dinner with friends')
                page.locator('#editor').screenshot(path=str(args.output / 'repayment.png'))
                assert not errors, errors
                context.close(); browser.close()
        finally:
            server.shutdown(); server.server_close(); thread.join()
    print('Captured three verified screenshots from synthetic records.')


if __name__ == '__main__':
    main()
