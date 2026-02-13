from odoo import models, fields


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # -------------------------------------------------------------------------
    # OVERDRAFT CONFIGURATION FIELDS
    # -------------------------------------------------------------------------
    overdraft_default_interest_rate = fields.Float(
        string='Default Interest Rate (%)',
        config_parameter='overdraft_interest_calculator.default_interest_rate',
        digits=(16, 6),
        default=0.0,
        help='Default daily interest rate applied to new overdraft records.',
    )
    overdraft_default_penalty_rate = fields.Float(
        string='Default Penalty Rate (%)',
        config_parameter='overdraft_interest_calculator.default_penalty_rate',
        digits=(16, 6),
        default=0.0,
        help='Default daily penalty rate applied to new overdraft records.',
    )
    overdraft_grace_period_days = fields.Integer(
        string='Grace Period (Days)',
        config_parameter='overdraft_interest_calculator.grace_period_days',
        default=0,
        help='Number of days before penalty starts being applied.',
    )
    overdraft_sequence_prefix = fields.Char(
        string='Reference Prefix',
        config_parameter='overdraft_interest_calculator.sequence_prefix',
        default='OD/',
        help='Prefix for overdraft reference numbers (e.g., OD/ → OD/0001).',
    )
