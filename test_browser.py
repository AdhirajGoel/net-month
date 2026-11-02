"""Optional local UI checks. Requires installed Playwright; uses only synthetic data."""
import argparse
import json
import tempfile
import threading
from pathlib import Path

from budget_server import BudgetHTTPServer, Handler, Store, empty, mutate, preview_import, commit_import, configure, ensure_month
from playwright.sync_api import sync_playwright, expect


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--screenshots', type=Path)
    args = parser.parse_args()
    if args.screenshots:
        args.screenshots.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as folder:
        state = empty()
        header = 'Date,Account,Description,Category,Amount\n'
        rows = [f'2026-10-{day % 28 + 1:02},Test card,Example purchase {day:02},Groceries,-20' for day in range(30)]
        rows += ['2026-09-15,Test card,Example App,Online Services,-20',
                 '2026-10-16,Test card,Example App,Online Services,-20']
        source = header + '\n'.join(rows) + '\n'
        preview = preview_import(state, source, 'initial.csv')
        commit_import(state, preview, {str(t['source_row']): 'add' for t in preview['rows']})
        mutate(state, 'transaction', dict(date='2026-09-10', amount='-10.01', description='Annual example',
               kind='expense', category='Miscellaneous', allocations=[{'month': m, 'amount': v} for m, v in
               [('2026-09', '3.34'), ('2026-10', '3.34'), ('2026-11', '3.33')]]))
        annual = state['transactions'][-1]['id']
        mutate(state, 'transaction', dict(date='2026-12-01', amount='1.00', description='Example refund',
               kind='refund', category='Miscellaneous'))
        credit = state['transactions'][-1]['id']
        store = Store(folder)
        store.save(state)
        upper = Path(folder) / 'EXPORT.CSV'
        upper.write_text(header + '2026-10-20,Test card,New gas,Gasoline/Fuel,-31\n')
        server = BudgetHTTPServer(('127.0.0.1', 0), Handler)
        server.store, server.token, server.previews = store, 'test-browser-token', {}
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(viewport={'width': 1360, 'height': 1000})
                page = context.new_page()
                errors, external = [], []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.on('request', lambda request: external.append(request.url) if not request.url.startswith('http://127.0.0.1:') else None)
                page.goto(f'http://127.0.0.1:{server.server_port}/')
                expect(page.locator('#save-status')).to_have_text('Saved locally')
                page.locator('#month-select').select_option('2026-10')
                if args.screenshots:
                    page.screenshot(path=str(args.screenshots / 'desktop.png'), full_page=True)

                # Tabs support roving focus and standard arrow/Home/End navigation.
                page.get_by_role('tab', name='Monthly', exact=True).focus()
                page.keyboard.press('ArrowRight')
                expect(page.get_by_role('tab', name='Transactions', exact=True)).to_be_focused()
                expect(page.get_by_role('tab', name='Transactions', exact=True)).to_have_attribute('aria-selected', 'true')
                page.keyboard.press('End')
                expect(page.get_by_role('tab', name='Review', exact=True)).to_be_focused()
                page.keyboard.press('Home')
                expect(page.get_by_role('tab', name='Monthly', exact=True)).to_be_focused()
                page.keyboard.press('ArrowLeft')
                expect(page.get_by_role('tab', name='Review', exact=True)).to_be_focused()
                page.get_by_role('tab', name='Transactions', exact=True).click()
                expect(page.locator('#page-status')).to_have_text('Page 1 of 2')
                page.get_by_role('button', name='Next', exact=True).click()
                expect(page.locator('#page-status')).to_have_text('Page 2 of 2')
                page.locator('#search').fill('Example App')
                expect(page.locator('#page-status')).to_have_text('Page 1 of 1')
                expect(page.locator('#ledger-rows tr')).to_have_count(2)
                expect(page.locator('#ledger-rows')).to_contain_text('Detected monthly subscription')
                page.get_by_role('button', name='Clear filters').click()
                page.locator('#sort-field').select_option('cents')
                page.locator('#sort-direction').select_option('desc')
                expect(page.locator('#ledger-rows tr').first).to_have_attribute('data-id', credit)
                page.get_by_role('tab', name='Monthly', exact=True).click()
                page.locator('[data-category=Gas]').click()
                expect(page.locator('#category-filter')).to_have_value('Gas')
                expect(page.locator('#ledger-rows')).to_contain_text('No matching transactions')
                page.get_by_role('button', name='Clear filters').click()

                # A refund restates the original allocation months down to the cent.
                page.locator('#search').fill('Example refund')
                page.get_by_role('button', name='Link credit', exact=True).click()
                page.locator('[data-field=expense_id]').select_option(annual)
                page.get_by_role('button', name='Save links', exact=True).click()
                expect(page.locator('#editor')).not_to_be_visible()
                totals = page.evaluate('Object.fromEntries(Object.entries(data.summaries).map(([m,s])=>[m,s.credits]))')
                assert totals == {'2026-09': 34, '2026-10': 33, '2026-11': 33, '2026-12': 0}, totals

                # A new draft follows its date; explicit allocations survive subsequent date edits.
                page.get_by_role('button', name='Add manual entry', exact=True).click()
                page.locator('[name=date]').fill('2026-09-12')
                page.locator('[name=description]').fill('Browser manual expense')
                expect(page.locator('[data-field=month]')).to_have_value('2026-09')
                page.locator('[data-field=month]').fill('2026-08')
                page.locator('[name=date]').fill('2026-10-12')
                page.locator('[name=amount]').fill('-10.01')
                expect(page.locator('[data-field=month]')).to_have_value('2026-08')
                page.locator('#split-start').fill('2026-09')
                page.locator('#split-count').fill('3')
                page.get_by_role('button', name='Split evenly', exact=True).click()
                assert page.locator('[data-field=amount]').evaluate_all('(es)=>es.map(e=>e.value)') == ['3.34', '3.34', '3.33']
                page.locator('[data-field=amount]').first.fill('1.00')
                page.get_by_role('button', name='Save transaction', exact=True).click()
                expect(page.locator('#editor-error')).to_contain_text('add up')
                expect(page.locator('[name=description]')).to_have_value('Browser manual expense')
                page.locator('[data-field=amount]').first.fill('3.34')
                page.get_by_role('button', name='Save transaction', exact=True).click()
                expect(page.locator('#editor')).not_to_be_visible()

                page.get_by_role('button', name='Add manual entry', exact=True).click()
                page.locator('[name=description]').fill('Empty allocation draft')
                page.get_by_role('button', name='Remove', exact=True).click()
                page.get_by_role('button', name='Save transaction', exact=True).click()
                expect(page.locator('#editor-error')).to_contain_text('Add at least one allocation')
                page.keyboard.press('Escape')

                # Folder imports accept uppercase extensions and exact overlaps remain explicit.
                page.get_by_role('button', name='Import CSV', exact=True).click()
                page.get_by_text('Or use a CSV already in the budget folder', exact=True).click()
                page.get_by_role('button', name='EXPORT.CSV', exact=True).click()
                expect(page.locator('#import-totals')).to_contain_text('1 to add')
                page.get_by_role('button', name='Confirm import', exact=True).click()
                expect(page.locator('#editor')).not_to_be_visible()
                assert upper.read_text().endswith('New gas,Gasoline/Fuel,-31\n')
                page.get_by_role('button', name='Import CSV', exact=True).click()
                reordered = header + '\n'.join(reversed(rows)) + '\n'
                page.locator('#import-file').set_input_files({'name': 'reordered.csv', 'mimeType': 'text/csv', 'buffer': reordered.encode()})
                expect(page.locator('#import-totals')).to_contain_text('32 to skip')
                assert page.locator('.import-choice').evaluate_all('(es)=>es.every(e=>e.value==="skip")')
                page.get_by_role('button', name='Confirm import', exact=True).click()
                expect(page.locator('#editor')).not_to_be_visible()
                page.get_by_role('button', name='Import CSV', exact=True).click()
                page.locator('#import-file').set_input_files({'name': 'reordered.csv', 'mimeType': 'text/csv', 'buffer': reordered.encode()})
                expect(page.locator('#import-preview')).to_contain_text('already been imported')
                page.keyboard.press('Escape')

                held = []
                page.route('**/api/preview', lambda route: held.append(route))
                page.get_by_role('button', name='Import CSV', exact=True).click()
                with page.expect_request('**/api/preview'):
                    page.locator('#import-file').set_input_files({'name': 'cancelled.csv', 'mimeType': 'text/csv', 'buffer': source.encode()})
                page.keyboard.press('Escape')
                page.get_by_role('button', name='Add manual entry', exact=True).click()
                held[0].abort()
                page.unroute('**/api/preview')
                expect(page.locator('#editor-title')).to_have_text('Add manual entry')
                expect(page.locator('#editor-error')).to_be_empty()
                page.keyboard.press('Escape')

                # Visibility survives reload; hidden records remain searchable on explicit request.
                page.get_by_role('button', name='Manage months', exact=True).click()
                for select in page.locator('[data-visibility]').all():
                    select.select_option('exclude')
                page.get_by_role('button', name='Apply visibility', exact=True).click()
                expect(page.locator('#month-heading')).to_have_text('All months hidden')
                page.reload()
                expect(page.locator('#month-heading')).to_have_text('All months hidden')
                page.get_by_role('tab', name='Transactions', exact=True).click()
                page.locator('#scope-filter').select_option('all')
                expect(page.locator('#ledger-rows tr')).to_have_count(25)
                page.get_by_role('button', name='Manage months', exact=True).click()
                page.get_by_role('button', name='Show all months', exact=True).click()
                page.get_by_role('button', name='Apply visibility', exact=True).click()
                page.locator('#month-select').select_option('2026-10')
                page.get_by_role('tab', name='Monthly', exact=True).click()

                for width, scheme, name in [(390, 'light', 'mobile'), (1360, 'dark', 'desktop-dark')]:
                    page.set_viewport_size({'width': width, 'height': 900})
                    page.emulate_media(color_scheme=scheme)
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    if width == 390:
                        assert page.locator('.bm-kpis').bounding_box()['y'] < 700
                    if args.screenshots:
                        page.screenshot(path=str(args.screenshots / f'{name}.png'), full_page=True)
                    page.get_by_role('button', name='Add manual entry', exact=True).click()
                    assert page.locator('#editor').bounding_box()['width'] <= width
                    page.keyboard.press('Escape')
                    page.get_by_role('tab', name='Transactions', exact=True).click()
                    page.get_by_role('button', name='Clear filters').click()
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    if args.screenshots and width == 390:
                        page.screenshot(path=str(args.screenshots / 'mobile-transactions.png'), full_page=True)
                    page.get_by_role('tab', name='Monthly', exact=True).click()
                page.get_by_role('tab', name='Trends', exact=True).click()
                expect(page.locator('.bm-history-col')).to_have_count(4)
                page.get_by_role('tab', name='Review', exact=True).click()
                expect(page.locator('#main-content')).to_contain_text('Confirm monthly coverage')

                # Confirmed writes remain successful even when the following GET fails.
                page.get_by_role('button', name='Add manual entry', exact=True).click()
                page.locator('[name=description]').fill('Saved despite failed reload')
                before = len(store.load()['transactions'])
                page.route('**/api/state', lambda route: route.abort())
                page.get_by_role('button', name='Save transaction', exact=True).click()
                expect(page.locator('#save-status')).to_have_text('Saved · reload needed')
                expect(page.locator('#editor')).not_to_be_visible()
                expect(page.locator('#global-message')).to_contain_text('Your change was saved')
                assert len(store.load()['transactions']) == before + 1
                page.unroute('**/api/state')
                page.get_by_role('button', name='Reload saved data', exact=True).click()
                expect(page.locator('#save-status')).to_have_text('Saved locally')
                assert len(store.load()['transactions']) == before + 1
                # A setup agent can supply entirely different category names and groups.
                config = {'categories': {'Home': 1000, 'Memberships': 30, 'Other': 100},
                          'category_map': {'rent': 'Home'}, 'subscription_category': 'Memberships',
                          'fallback_category': 'Other', 'groups': {'Essentials': ['Home'], 'Flexible': ['Memberships', 'Other']}}
                config_path = Path(folder) / 'config.json'
                config_path.write_text(json.dumps(config))
                configure(config_path)
                custom = empty(); ensure_month(custom, '2026-10'); store.save(custom)
                page.reload()
                expect(page.locator('#save-status')).to_have_text('Saved locally')
                expect(page.locator('#sidebar')).to_contain_text('Essentials')
                expect(page.locator('#sidebar')).to_contain_text('$1,000.00')
                assert 'NaN' not in page.locator('body').inner_text()
                page.get_by_role('button', name='Add manual entry', exact=True).click()
                expect(page.locator('#edit-category')).to_have_value('Other')
                page.locator('[name=description]').fill('Custom category example')
                page.get_by_role('button', name='Save transaction', exact=True).click()
                expect(page.locator('#editor')).not_to_be_visible()
                assert store.load()['transactions'][0]['category'] == 'Other'
                assert not errors, errors
                assert not external, external
                context.close()
                browser.close()
            print('Browser flows passed: tabs, filters, sorting, pagination, refunds, allocations, save rejection/recovery, imports, visibility, desktop/mobile/dark layout. No external requests.')
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__':
    main()
