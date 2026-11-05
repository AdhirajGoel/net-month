"""Create a synthetic budget in a new data directory; never overwrite records."""
import argparse
import json
from pathlib import Path

from budget_server import Store, empty, preview_import, commit_import, mutate, configure


DEMO_CONFIG = {
    'categories': dict(zip([f'Category {i}' for i in range(1, 8)], [400, 300, 300, 500, 300, 100, 100])),
    'category_map': {'rent': 'Category 1', 'car loan': 'Category 2', 'auto insurance': 'Category 3',
                     'groceries': 'Category 4', 'restaurants': 'Category 4', 'gasoline/fuel': 'Category 5'},
    'subscription_category': 'Category 6',
    'fallback_category': 'Category 7',
    'groups': {'Needs': [f'Category {i}' for i in range(1, 6)], 'Wants': ['Category 6', 'Category 7']},
}


def demo_state():
    """Build the synthetic records after loading DEMO_CONFIG."""
    rows = ['Date,Account,Description,Category,Amount']
    for month in ['2026-08', '2026-09', '2026-10']:
        for day, merchant, category, amount in [
            (1, 'Example Apartments', 'Rent', -400),
            (3, 'Example Auto Loan', 'Car loan', -300),
            (5, 'Example Grocery', 'Groceries', -200),
            (8, 'Example Fuel', 'Gasoline/Fuel', -200),
            (15, 'Example Music', 'Online Services', -100),
        ]:
            rows.append(f'{month}-{day:02},Demo checking,{merchant},{category},{amount}')
    rows += [
        '2026-08-10,Demo card,Annual insurance,Auto Insurance,-3600',
        '2026-10-20,Demo card,Insurance refund,Auto Insurance,1200',
        '2026-10-12,Demo card,Dinner with friends,Restaurants,-300',
        '2026-11-02,Demo checking,Dinner repayment,Restaurants,100',
    ]
    state = empty()
    preview = preview_import(state, '\n'.join(rows) + '\n', 'synthetic-empower.csv')
    commit_import(state, preview, {str(t['source_row']): 'add' for t in preview['rows']})
    by_name = {t['description']: t for t in state['transactions']}
    annual = by_name['Annual insurance']
    months = [f'{2026 + (7 + i) // 12}-{(7 + i) % 12 + 1:02}' for i in range(12)]
    mutate(state, 'transaction', dict(id=annual['id'], kind='expense', category='Category 3',
           allocations=[{'month': month, 'amount': '300'} for month in months]))
    mutate(state, 'links', {'id': by_name['Insurance refund']['id'],
           'links': [{'expense_id': annual['id'], 'amount': '1200'}]})
    repayment = by_name['Dinner repayment']
    mutate(state, 'transaction', dict(id=repayment['id'], kind='reimbursement', category='Category 4'))
    mutate(state, 'links', {'id': repayment['id'],
           'links': [{'expense_id': by_name['Dinner with friends']['id'], 'amount': '100'}]})
    for month in ['2026-08', '2026-09', '2026-10']:
        mutate(state, 'month', {'month': month, 'zero_categories': ['Category 7'], 'reviewed': True})
    return state


def create_demo(folder):
    folder = Path(folder)
    # Exclusive creation prevents mixing demo records with anyone's financial data.
    folder.mkdir(parents=True, exist_ok=False, mode=0o700)
    config = folder / 'config.json'
    config.write_text(json.dumps(DEMO_CONFIG, indent=2) + '\n', encoding='utf-8')
    configure(config)
    Store(folder).save(demo_state())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=Path(__file__).parent / 'demo-data')
    args = parser.parse_args()
    create_demo(args.data_dir)
    print('Synthetic demo created. Launch with: python3 budget_server.py --data-dir ' + str(args.data_dir))
