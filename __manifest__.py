{
    'name': 'Overdraft Interest Calculator',
    'version': '18.0.1.0.0',
    'category': 'Accounting',
    'summary': 'Calculate daily interest and penalties for bank overdrafts',
    'description': """
        Overdraft Interest Calculator
        =============================
        Track bank overdraft accounts and automatically calculate
        daily interest and penalties. Features include:
        - Multiple overdraft records per bank account
        - Auto-computed interest and penalty per line
        - Running balance tracking
        - Approval workflow (Draft → Submitted → Approved → Closed)
        - Status dashboard for active overdrafts
        - Configurable default rates and grace periods
    """,
    'author': 'Eyosias Yitay',
    'license': 'LGPL-3',
    'depends': ['base', 'mail', 'account'],
    'data': [
        # Security first
        'security/overdraft_groups.xml',
        'security/ir.model.access.csv',
        # Data
        'data/ir_sequence_data.xml',
        # Views
        'views/overdraft_line_views.xml',
        'views/overdraft_interest_views.xml',
        'views/menu_items.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
