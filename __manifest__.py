{
    'name': 'Loan Management',
    'version': '18.0.4.1.0',
    'category': 'Accounting',
    'summary': 'Manage overdraft, term, merchandise, and pre-shipment loans',
    'description': """
        Loan Management
        ================
        Comprehensive loan management solution including:

        - Overdraft Interest: Daily balance tracking, auto-interest/penalty, approval workflow
        - Term Loan: Full amortization schedule, extra payments, manager approval
        - Merchandise Loan: Bank-financed goods purchase with warehouse collateral and payment/goods release tracking
        - Pre-Shipment Loan: Export financing with foreign currency commitment tracking and penalty management
        - Unified Dashboard: Tabbed KPI dashboard with Bank and Time filters for all 4 loan types
    """,
    'author': 'Eyosias Yitay',
    'license': 'LGPL-3',
    'depends': ['base', 'mail', 'account', 'stock', 'web'],
    'data': [
        # Security
        'security/overdraft_groups.xml',
        'security/ir.model.access.csv',
        # Data
        'data/ir_sequence_data.xml',
        # Views — Overdraft
        'views/overdraft_line_views.xml',
        'views/overdraft_interest_views.xml',
        # Views — Term Loan
        'views/term_loan_views.xml',
        'views/term_loan_line_views.xml',
        # Views — Merchandise Loan
        'views/merchandise_loan_views.xml',
        # Views — Pre-Shipment Loan
        'views/preshipment_loan_views.xml',
        # Dashboard
        'views/dashboard_views.xml',
        # Wizards
        'wizard/payment_wizard_views.xml',
        # Menus (always last)
        'views/menu_items.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'overdraft_interest_calculator/static/src/css/loan_dashboard.css',
            'overdraft_interest_calculator/static/src/components/loan_dashboard.xml',
            'overdraft_interest_calculator/static/src/components/loan_dashboard.js',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
