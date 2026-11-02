"""Create a synthetic budget in a new data directory; never overwrite records."""
import argparse
from pathlib import Path

from budget_server import Store, empty, preview_import, commit_import, mutate, CATEGORIES


def demo_state():
    rows = ['Date,Account,Description,Category,Amount']
    for month in ['2026-08', '2026-09', '2026-10']:
        for day, merchant, category, amount in [
            (1, 'Example Apartments', 'Rent', -1800),
            (3, 'Example Auto Loan', 'Car loan', -250),
            (5, 'Example Grocery', 'Groceries', -320),
            (8, 'Example Fuel', 'Gasoline/Fuel', -60),
            (15, 'Example Music', 'Online Services', -18),
        ]:
            rows.append(f'{month}-{day:02},Demo checking,{merchant},{category},{amount}')
    rows += [
        '2026-08-10,Demo card,Annual insurance,Auto Insurance,-1200',
        '2026-10-20,Demo card,Insurance refund,Auto Insurance,240',
        '2026-10-12,Demo card,Dinner with friends,Restaurants,-120',
        '2026-11-02,Demo checking,Dinner repayment,Restaurants,80',
    ]
    state = empty()
    preview = preview_import(state, '\n'.join(rows) + '\n', 'synthetic-empower.csv')
    commit_import(state, preview, {str(t['source_row']): 'add' for t in preview['rows']})
    by_name = {t['description']: t for t in state['transactions']}
    annual = by_name['Annual insurance']
    months = [f'{2026 + (7 + i) // 12}-{(7 + i) % 12 + 1:02}' for i in range(12)]
    mutate(state, 'transaction', dict(id=annual['id'], kind='expense', category='Auto insurance',
           allocations=[{'month': month, 'amount': '100'} for month in months]))
    mutate(state, 'links', {'id': by_name['Insurance refund']['id'],
           'links': [{'expense_id': annual['id'], 'amount': '240'}]})
    repayment = by_name['Dinner repayment']
    mutate(state, 'transaction', dict(id=repayment['id'], kind='reimbursement', category='Groceries+Food'))
    mutate(state, 'links', {'id': repayment['id'],
           'links': [{'expense_id': by_name['Dinner with friends']['id'], 'amount': '80'}]})
    plan = dict(zip(CATEGORIES, [180000, 25000, 10000, 45000, 8000, 5000, 25000]))
    for month in state['budgets']:
        state['budgets'][month] = plan.copy()
    for month in ['2026-08', '2026-09', '2026-10']:
        mutate(state, 'month', {'month': month, 'zero_categories': ['Miscellaneous'], 'reviewed': True})
    return state


def create_demo(folder):
    folder = Path(folder)
    # Exclusive creation prevents mixing demo records with anyone's financial data.
    folder.mkdir(parents=True, exist_ok=False, mode=0o700)
    Store(folder).save(demo_state())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=Path(__file__).parent / 'demo-data')
    args = parser.parse_args()
    create_demo(args.data_dir)
    print('Synthetic demo created. Launch with: python3 budget_server.py --data-dir ' + str(args.data_dir))
