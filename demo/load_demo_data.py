"""
Fix-up demo data loader — only creates Term Loan, Merchandise, and Pre-Shipment records.
(Overdraft records were already created in the previous run.)
"""
from datetime import date, timedelta

env = env  # noqa

today = date.today()

def get_bank_journal(index=0):
    journals = env['account.journal'].search([('type', '=', 'bank')], limit=5)
    return journals[index % len(journals)] if journals else None

def get_currency():
    return env.company.currency_id

def get_foreign_currency():
    cur = env['res.currency'].search([('name', '=', 'USD')], limit=1)
    if not cur:
        cur = env['res.currency'].search([('name', '!=', env.company.currency_id.name)], limit=1)
    return cur or env.company.currency_id

def get_product():
    return env['product.product'].search([], limit=1)

def get_warehouse():
    return env['stock.warehouse'].search([], limit=1)

def get_account(account_type):
    return env['account.account'].search([('account_type', '=', account_type)], limit=1)

currency = get_currency()
foreign_curr = get_foreign_currency()
product = get_product()
warehouse = get_warehouse()
j1 = get_bank_journal(0)
j2 = get_bank_journal(1)
receivable = get_account('asset_receivable')
payable = get_account('liability_payable')
income = get_account('income')
expense = get_account('expense')

print(f"Bank journals: {j1.name} (id={j1.id}), {j2.name} (id={j2.id})")
print(f"Currency: {currency.name}, Foreign: {foreign_curr.name}")
print(f"Product: {product.name if product else 'None'}")
print(f"Warehouse: {warehouse.name if warehouse else 'None'}")

# ══════════════════════════════════════════════════════════════════════════════
# 2. TERM LOANS
# ══════════════════════════════════════════════════════════════════════════════
print("\n--- Creating Term Loan records ---")

tl1 = env['term.loan'].create({
    'lender_name': j1.id,
    'loan_amount': 40_000_000,
    'annual_interest_rate': 0.1825,
    'loan_period_years': 3,
    'payments_per_year': '12',
    'start_date': today - timedelta(days=365),
    'currency_id': currency.id,
    'account_receivable_id': receivable.id if receivable else False,
    'account_payable_id': payable.id if payable else False,
    'income_account_id': income.id if income else False,
    'expense_account_id': expense.id if expense else False,
})
tl1.state = 'submitted'
tl1.state = 'approved'
tl1.action_generate_schedule()
for line in tl1.loan_line_ids[:5]:
    line.extra_payment = 200_000
print(f"  Created TL1: {tl1.name} — 40M ETB, 3yr monthly")

tl2 = env['term.loan'].create({
    'lender_name': j2.id,
    'loan_amount': 25_000_000,
    'annual_interest_rate': 0.165,
    'loan_period_years': 5,
    'payments_per_year': '12',
    'start_date': today - timedelta(days=180),
    'currency_id': currency.id,
    'account_receivable_id': receivable.id if receivable else False,
    'account_payable_id': payable.id if payable else False,
    'income_account_id': income.id if income else False,
    'expense_account_id': expense.id if expense else False,
})
tl2.state = 'submitted'
tl2.state = 'approved'
tl2.action_generate_schedule()
print(f"  Created TL2: {tl2.name} — 25M ETB, 5yr monthly")

# ══════════════════════════════════════════════════════════════════════════════
# 3. MERCHANDISE LOANS
# ══════════════════════════════════════════════════════════════════════════════
print("\n--- Creating Merchandise Loan records ---")

if product and warehouse:
    ml1 = env['merchandise.loan'].create({
        'bank_journal_id': j1.id,
        'product_id': product.id,
        'goods_quantity': 500,
        'goods_unit_price': 12_000,
        'warehouse_id': warehouse.id,
        'bank_coverage_percent': 70.0,
        'annual_interest_rate': 16.5,
        'date_from': today - timedelta(days=45),
        'date_to': today + timedelta(days=90),
        'currency_id': currency.id,
        'account_receivable_id': receivable.id if receivable else False,
        'account_payable_id': payable.id if payable else False,
        'income_account_id': income.id if income else False,
        'expense_account_id': expense.id if expense else False,
    })
    env['merchandise.loan.line'].create([
        {'loan_id': ml1.id, 'date': today - timedelta(days=30),
         'payment_amount': 1_400_000, 'goods_released_quantity': 167,
         'interest': 32_000, 'outstanding_balance': 4_726_000},
        {'loan_id': ml1.id, 'date': today - timedelta(days=15),
         'payment_amount': 1_400_000, 'goods_released_quantity': 167,
         'interest': 28_500, 'outstanding_balance': 3_326_000},
        {'loan_id': ml1.id, 'date': today,
         'payment_amount': 700_000, 'goods_released_quantity': 83,
         'interest': 23_000, 'outstanding_balance': 2_626_000},
    ])
    ml1.state = 'active'
    print(f"  Created ML1: {ml1.name} — goods 6M, 70/30")

    ml2 = env['merchandise.loan'].create({
        'bank_journal_id': j2.id,
        'product_id': product.id,
        'goods_quantity': 1000,
        'goods_unit_price': 8_500,
        'warehouse_id': warehouse.id,
        'bank_coverage_percent': 75.0,
        'annual_interest_rate': 18.0,
        'date_from': today - timedelta(days=20),
        'date_to': today + timedelta(days=120),
        'currency_id': currency.id,
        'account_receivable_id': receivable.id if receivable else False,
        'account_payable_id': payable.id if payable else False,
        'income_account_id': income.id if income else False,
        'expense_account_id': expense.id if expense else False,
    })
    env['merchandise.loan.line'].create([
        {'loan_id': ml2.id, 'date': today - timedelta(days=10),
         'payment_amount': 2_125_000, 'goods_released_quantity': 333,
         'interest': 35_000, 'outstanding_balance': 4_250_000},
    ])
    ml2.state = 'active'
    print(f"  Created ML2: {ml2.name} — goods 8.5M, 75/25")
else:
    print(f"  Skipped — product={bool(product)}, warehouse={bool(warehouse)}")

# ══════════════════════════════════════════════════════════════════════════════
# 4. PRE-SHIPMENT LOANS
# ══════════════════════════════════════════════════════════════════════════════
print("\n--- Creating Pre-Shipment Loan records ---")

# ps1 = env['preshipment.loan'].create({
#     'bank_journal_id': j1.id,
#     'loan_amount': 15_000_000,
#     'annual_interest_rate': 14.5,
#     'penalty_rate': 3.0,
#     'currency_id': currency.id,
#     'foreign_currency_id': foreign_curr.id,
#     'total_currency_to_store': 320_000,
#     'start_date': today - timedelta(days=60),
#     'expected_export_date': today + timedelta(days=90),
#     'financed_goods_description': 'Coffee export — Grade 1, 120 MT',
#     'financed_goods_value': 18_000_000,
#     'account_receivable_id': receivable.id if receivable else False,
#     'account_payable_id': payable.id if payable else False,
#     'income_account_id': income.id if income else False,
#     'expense_account_id': expense.id if expense else False,
# })
# env['preshipment.loan.line'].create([
#     {'loan_id': ps1.id, 'date': today - timedelta(days=55),
#      'amount_used': 5_000_000, 'currency_deposited': 0, 'interest': 19_863, 'penalty': 0},
#     {'loan_id': ps1.id, 'date': today - timedelta(days=30),
#      'amount_used': 7_000_000, 'currency_deposited': 80_000, 'interest': 27_808, 'penalty': 0},
#     {'loan_id': ps1.id, 'date': today - timedelta(days=10),
#      'amount_used': 3_000_000, 'currency_deposited': 50_000, 'interest': 11_918, 'penalty': 0},
# ])
# ps1.state = 'active'
# print(f"  Created PS1: {ps1.name} — 15M ETB, {foreign_curr.name} 320K")

# ps2 = env['preshipment.loan'].create({
#     'bank_journal_id': j2.id,
#     'loan_amount': 10_000_000,
#     'annual_interest_rate': 16.0,
#     'penalty_rate': 4.5,
#     'currency_id': currency.id,
#     'foreign_currency_id': foreign_curr.id,
#     'total_currency_to_store': 200_000,
#     'start_date': today - timedelta(days=30),
#     'expected_export_date': today + timedelta(days=60),
#     'financed_goods_description': 'Sesame seed export — 80 MT',
#     'financed_goods_value': 11_500_000,
#     'account_receivable_id': receivable.id if receivable else False,
#     'account_payable_id': payable.id if payable else False,
#     'income_account_id': income.id if income else False,
#     'expense_account_id': expense.id if expense else False,
# })
# env['preshipment.loan.line'].create([
#     {'loan_id': ps2.id, 'date': today - timedelta(days=25),
#      'amount_used': 6_000_000, 'currency_deposited': 30_000, 'interest': 26_301, 'penalty': 0},
#     {'loan_id': ps2.id, 'date': today - timedelta(days=10),
#      'amount_used': 4_000_000, 'currency_deposited': 20_000, 'interest': 17_534, 'penalty': 0},
# ])
# ps2.state = 'active'
# print(f"  Created PS2: {ps2.name} — 10M ETB, {foreign_curr.name} 200K")

# env.cr.commit()
# print("\n✅ All remaining demo data created and committed!")
