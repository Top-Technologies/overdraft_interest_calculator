import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class PreShipmentLoan(models.Model):
    _name = 'preshipment.loan'
    _description = 'Pre-Shipment Loan'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'start_date desc, id desc'

    # -------------------------------------------------------------------------
    # DEFAULT HELPERS
    # -------------------------------------------------------------------------
    @api.model
    def _default_currency(self):
        return self.env.company.currency_id

    # -------------------------------------------------------------------------
    # FIELDS — Identity
    # -------------------------------------------------------------------------
    name = fields.Char(
        string='Reference',
        required=True,
        copy=False,
        readonly=True,
        default='New',
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('active', 'Active'),
        ('closed', 'Closed'),
    ], string='Status', default='draft', tracking=True, copy=False)

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        tracking=True,
    )

    # -------------------------------------------------------------------------
    # FIELDS — Bank
    # -------------------------------------------------------------------------
    bank_journal_id = fields.Many2one(
        'account.journal',
        string='Bank Journal',
        required=True,
        domain="[('type', '=', 'bank')]",
        tracking=True,
    )
    bank_id = fields.Many2one(
        'res.bank',
        string='Bank',
        related='bank_journal_id.bank_id',
        store=True,
        readonly=True,
    )

    # -------------------------------------------------------------------------
    # FIELDS — Dates and Local Currency
    # -------------------------------------------------------------------------
    start_date = fields.Date(
        string='Start Date',
        default=fields.Date.context_today,
        required=True,
        tracking=True,
    )
    expected_export_date = fields.Date(
        string='Expected Export / Currency Delivery Date',
        required=True,
        tracking=True,
        help='Agreed date by which the foreign currency must be deposited to the bank',
    )
    end_date = fields.Date(
        string='End Date',
        tracking=True,
        help='Loan maturity date — the final date by which the export loan must be '
             'fully repaid or settled.',
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Local Currency',
        default=_default_currency,
        required=True,
    )

    # -------------------------------------------------------------------------
    # FIELDS — Loan Details (Local Currency)
    # -------------------------------------------------------------------------
    loan_amount = fields.Monetary(
        string='Loan Amount (Given by Bank)',
        currency_field='currency_id',
        required=True,
        tracking=True,
        help='Total amount lent by the bank in local currency',
    )
    loan_used = fields.Monetary(
        string='Loan Used',
        currency_field='currency_id',
        compute='_compute_loan_usage',
        store=True,
        help='Amount of the loan already utilised',
    )
    loan_remaining = fields.Monetary(
        string='Loan Remaining',
        currency_field='currency_id',
        compute='_compute_loan_usage',
        store=True,
    )

    # -------------------------------------------------------------------------
    # FIELDS — Foreign Currency Commitment
    # -------------------------------------------------------------------------
    foreign_currency_id = fields.Many2one(
        'res.currency',
        string='Foreign Currency',
        required=True,
        tracking=True,
        help='The foreign currency to be deposited to the bank upon export (e.g. USD)',
    )
    total_currency_to_store = fields.Float(
        string='Total Currency to Deliver to Bank',
        digits=(16, 4),
        required=True,
        tracking=True,
        help='Total amount of foreign currency promised to the bank',
    )
    currency_stored = fields.Float(
        string='Currency Already Stored',
        digits=(16, 4),
        compute='_compute_currency_progress',
        store=True,
    )
    currency_remaining = fields.Float(
        string='Currency Still Required',
        digits=(16, 4),
        compute='_compute_currency_progress',
        store=True,
    )
    currency_fulfillment_percent = fields.Float(
        string='Fulfillment (%)',
        compute='_compute_currency_progress',
        store=True,
        digits=(5, 2),
    )

    # -------------------------------------------------------------------------
    # FIELDS — Sales Orders
    # -------------------------------------------------------------------------
    sale_order_ids = fields.Many2many(
        'sale.order',
        'preshipment_loan_sale_order_rel',
        'loan_id',
        'sale_order_id',
        string='Sales Orders',
        tracking=True,
        help='Sales orders linked to this pre-shipment loan. A loan may be linked '
             'to one or more sales orders — create a new one or link an existing '
             'one from this list.',
    )
    sale_order_count = fields.Integer(
        string='Sales Order Count',
        compute='_compute_sale_order_count',
    )

    # -------------------------------------------------------------------------
    # FIELDS — Raw Material Financed
    # -------------------------------------------------------------------------
    raw_material_description = fields.Text(
        string='Raw Material Description',
        tracking=True,
        help='Description of the raw materials financed under this loan facility.',
    )
    raw_material_qty = fields.Float(
        string='Raw Material Quantity',
        digits='Product Unit of Measure',
        tracking=True,
        help='Quantity of raw materials financed under the loan facility for '
             'export preparation or production.',
    )
    raw_material_uom_id = fields.Many2one(
        'uom.uom',
        string='Unit of Measure',
        tracking=True,
    )
    raw_material_value = fields.Monetary(
        string='Raw Material Value',
        currency_field='currency_id',
        tracking=True,
        help='Monetary value of the raw materials financed under the loan facility.',
    )

    # -------------------------------------------------------------------------
    # FIELDS — Export Proceeds & Settlement
    # -------------------------------------------------------------------------
    export_proceeds_foreign_amount = fields.Float(
        string='Export Proceeds Received (Foreign Currency)',
        digits=(16, 4),
        compute='_compute_export_proceeds',
        store=True,
        help='Actual amount collected from the foreign buyer after the export '
             'transaction, in foreign currency.',
    )
    export_proceeds_local_amount = fields.Monetary(
        string='Export Proceeds Received (Local Equivalent)',
        currency_field='currency_id',
        compute='_compute_export_proceeds',
        store=True,
        help='Export proceeds received, converted into local currency equivalent.',
    )
    loan_settled_amount = fields.Monetary(
        string='Loan Settled Amount',
        currency_field='currency_id',
        compute='_compute_loan_settled_amount',
        help='Portion of the export proceeds used to repay or settle this '
             'pre-shipment export loan facility.',
    )
    company_remaining_amount = fields.Monetary(
        string='Company Remaining Amount',
        currency_field='currency_id',
        compute='_compute_company_remaining_amount',
        help='Money remaining for the company after the bank has deducted the settled amount.',
    )
    outstanding_balance = fields.Monetary(
        string='Outstanding Balance',
        currency_field='currency_id',
        compute='_compute_outstanding_balance',
        help='Remaining unpaid amount of the loan exposure after repayments or '
             'settlements have been applied. Includes unpaid principal, interest '
             'and penalty charges.',
    )

    # -------------------------------------------------------------------------
    # FIELDS — Purpose & Collateral
    # -------------------------------------------------------------------------
    purpose = fields.Text(
        string='Purpose',
        tracking=True,
        help='Intended use of the pre-shipment loan (e.g. sesame procurement, soya meal processing).',
    )
    collateral_document_ids = fields.Many2many(
        'ir.attachment',
        'preshipment_loan_collateral_attachment_rel',
        'loan_id',
        'attachment_id',
        string='Collateral Documents',
        help='Attach export contracts, LC documents, guarantees, or other collateral documents.',
    )

    # -------------------------------------------------------------------------
    # FIELDS — Interest & Penalty
    # -------------------------------------------------------------------------
    annual_interest_rate = fields.Float(
        string='Annual Interest Rate (%)',
        digits=(16, 6),
        required=True,
        tracking=True,
    )
    penalty_rate_tier1 = fields.Float(
        string='Penalty Rate — Days 1–30 (% p.a.)',
        digits=(16, 6),
        default=0.0,
        tracking=True,
        help='Annual penalty rate applied for every day in the first 30 days past the expected export date.',
    )
    penalty_rate_tier2 = fields.Float(
        string='Penalty Rate — Days 31–60 (% p.a.)',
        digits=(16, 6),
        default=0.0,
        tracking=True,
        help='Annual penalty rate applied for every day between 31 and 60 days past the expected export date.',
    )
    penalty_rate_tier3 = fields.Float(
        string='Penalty Rate — Days 60+ (% p.a.)',
        digits=(16, 6),
        default=0.0,
        tracking=True,
        help='Annual penalty rate applied for every day beyond 60 days past the expected export date.',
    )
    penalty_amount = fields.Monetary(
        string='Penalty Amount',
        currency_field='currency_id',
        compute='_compute_penalty',
    )
    total_interest = fields.Monetary(
        string='Total Interest',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
    )

    # -------------------------------------------------------------------------
    # FIELDS — Lines
    # -------------------------------------------------------------------------
    loan_line_ids = fields.One2many(
        'preshipment.loan.line',
        'loan_id',
        string='Utilisation & Currency Entries',
    )

    # -------------------------------------------------------------------------
    # FIELDS — Accounting Links
    # -------------------------------------------------------------------------
    move_ids = fields.One2many(
        'account.move', 'preshipment_loan_id',
        string='Journal Entries',
    )
    bill_ids = fields.One2many(
        'account.move', 'preshipment_loan_id',
        string='Bills',
        domain=[('move_type', '=', 'in_invoice')],
    )
    move_count = fields.Integer(
        compute='_compute_move_count',
        string='Journal Entry Count',
    )
    bill_count = fields.Integer(
        compute='_compute_move_count',
        string='Bill Count',
    )

    # -------------------------------------------------------------------------
    # FIELDS — Account Links
    # -------------------------------------------------------------------------
    account_receivable_id = fields.Many2one(
        'account.account',
        string='Account Receivable',
        tracking=True,
        domain="[('account_type', '=', 'asset_receivable')]",
    )
    account_payable_id = fields.Many2one(
        'account.account',
        string='Account Payable',
        tracking=True,
        domain="[('account_type', '=', 'liability_payable')]",
    )
    income_account_id = fields.Many2one(
        'account.account',
        string='Income Account',
        tracking=True,
        domain="[('account_type', 'in', ('income', 'income_other'))]",
    )
    expense_account_id = fields.Many2one(
        'account.account',
        string='Expense Account',
        tracking=True,
        domain="[('account_type', 'in', ('expense', 'expense_depreciation', 'expense_direct_cost'))]",
    )

    # -------------------------------------------------------------------------
    # COMPUTE METHODS
    # -------------------------------------------------------------------------
    def _compute_move_count(self):
        for rec in self:
            moves = self.env['account.move'].search([
                ('preshipment_loan_id', '=', rec.id),
            ])
            rec.move_count = len(moves.filtered(lambda m: m.move_type == 'entry'))
            rec.bill_count = len(moves.filtered(lambda m: m.move_type == 'in_invoice'))

    @api.depends('loan_line_ids.amount_used')
    def _compute_loan_usage(self):
        for rec in self:
            used = sum(l.amount_used for l in rec.loan_line_ids)
            rec.loan_used = used
            rec.loan_remaining = max(rec.loan_amount - used, 0.0)

    @api.depends('loan_line_ids.currency_deposited')
    def _compute_currency_progress(self):
        for rec in self:
            stored = sum(l.currency_deposited for l in rec.loan_line_ids)
            rec.currency_stored = stored
            rec.currency_remaining = max(rec.total_currency_to_store - stored, 0.0)
            if rec.total_currency_to_store:
                rec.currency_fulfillment_percent = round(
                    stored / rec.total_currency_to_store, 4
                )
            else:
                rec.currency_fulfillment_percent = 0.0

    @api.depends('loan_line_ids.interest')
    def _compute_totals(self):
        for rec in self:
            rec.total_interest = sum(l.interest for l in rec.loan_line_ids)

    @api.depends('sale_order_ids')
    def _compute_sale_order_count(self):
        for rec in self:
            rec.sale_order_count = len(rec.sale_order_ids)

    @api.depends('loan_line_ids.entry_type', 'loan_line_ids.currency_deposited', 'loan_line_ids.amount_deposited_local')
    def _compute_export_proceeds(self):
        for rec in self:
            foreign = sum(l.currency_deposited for l in rec.loan_line_ids if l.entry_type == 'currency')
            local = sum(l.amount_deposited_local for l in rec.loan_line_ids if l.entry_type == 'currency')
            rec.export_proceeds_foreign_amount = foreign
            rec.export_proceeds_local_amount = local

    @api.depends('export_proceeds_local_amount', 'loan_used', 'total_interest', 'penalty_amount')
    def _compute_loan_settled_amount(self):
        for rec in self:
            total_due = rec.loan_used + rec.total_interest + rec.penalty_amount
            if rec.export_proceeds_local_amount:
                rec.loan_settled_amount = min(rec.export_proceeds_local_amount, total_due)
            else:
                rec.loan_settled_amount = 0.0

    @api.depends('export_proceeds_local_amount', 'loan_settled_amount')
    def _compute_company_remaining_amount(self):
        for rec in self:
            if rec.export_proceeds_local_amount:
                rec.company_remaining_amount = max(rec.export_proceeds_local_amount - rec.loan_settled_amount, 0.0)
            else:
                rec.company_remaining_amount = 0.0

    @api.depends('loan_used', 'total_interest', 'penalty_amount', 'loan_settled_amount')
    def _compute_outstanding_balance(self):
        for rec in self:
            rec.outstanding_balance = max(
                rec.loan_used + rec.total_interest + rec.penalty_amount
                - rec.loan_settled_amount,
                0.0,
            )

    @api.depends(
        'currency_remaining', 'penalty_rate_tier1', 'penalty_rate_tier2', 'penalty_rate_tier3',
        'loan_used', 'expected_export_date',
    )
    def _compute_penalty(self):
        from datetime import date
        for rec in self:
            if (
                rec.expected_export_date
                and rec.expected_export_date < date.today()
                and rec.currency_remaining > 0
            ):
                days_overdue = (date.today() - rec.expected_export_date).days
                principal = rec.loan_used

                # Split overdue days into the three penalty tiers
                tier1_days = min(days_overdue, 30)
                tier2_days = min(max(days_overdue - 30, 0), 30)
                tier3_days = max(days_overdue - 60, 0)

                penalty = 0.0
                if tier1_days > 0 and rec.penalty_rate_tier1:
                    penalty += principal * (rec.penalty_rate_tier1 / 100.0 / 365.0) * tier1_days
                if tier2_days > 0 and rec.penalty_rate_tier2:
                    penalty += principal * (rec.penalty_rate_tier2 / 100.0 / 365.0) * tier2_days
                if tier3_days > 0 and rec.penalty_rate_tier3:
                    penalty += principal * (rec.penalty_rate_tier3 / 100.0 / 365.0) * tier3_days

                rec.penalty_amount = round(penalty, 2)
            else:
                rec.penalty_amount = 0.0

    @api.constrains('annual_interest_rate')
    def _check_interest_rate(self):
        for record in self:
            if record.annual_interest_rate < 0:
                raise ValidationError(_('Interest rate cannot be negative.'))

    # -------------------------------------------------------------------------
    # SEQUENCE
    # -------------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('purpose'):
                raise UserError(_("Loan Purpose is compulsory when creating a new loan."))
            col = vals.get('collateral_document_ids')
            has_doc = False
            if col and isinstance(col, (list, tuple)):
                for cmd in col:
                    if isinstance(cmd, (list, tuple)):
                        if cmd[0] == 6 and cmd[2]:
                            has_doc = True
                        elif cmd[0] in (4, 0, 1, 2):
                            has_doc = True
            if not has_doc:
                raise UserError(_("At least one Collateral Document must be attached when creating a new loan."))

            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('preshipment.loan') or 'New'
        return super().create(vals_list)

    # -------------------------------------------------------------------------
    # WORKFLOW ACTIONS
    # -------------------------------------------------------------------------
    def action_submit(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only draft records can be submitted.'))
            rec.state = 'submitted'

    def action_approve(self):
        for rec in self:
            if rec.state != 'submitted':
                raise UserError(_('Only submitted records can be approved.'))
            rec.state = 'approved'

    def action_reject(self):
        for rec in self:
            if rec.state != 'submitted':
                raise UserError(_('Only submitted records can be rejected.'))
            rec.state = 'rejected'

    def action_activate(self):
        for rec in self:
            if rec.state != 'approved':
                raise UserError(_('Only approved records can be activated.'))
            # Create disbursement journal entry
            rec._create_disbursement_journal_entry()
            rec.state = 'active'

    def action_close(self):
        for rec in self:
            if rec.state != 'active':
                raise UserError(_('Only active loans can be closed.'))
            rec.state = 'closed'

    def action_reset_to_draft(self):
        for rec in self:
            if rec.state not in ('rejected', 'submitted'):
                raise UserError(_(
                    'Only rejected or submitted records can be reset to draft.'
                ))
            rec.state = 'draft'

    # -------------------------------------------------------------------------
    # ACCOUNTING METHODS
    # -------------------------------------------------------------------------
    def _create_disbursement_journal_entry(self):
        """Create a journal entry for pre-shipment loan disbursement."""
        for rec in self:
            if not rec.account_payable_id:
                raise UserError(_(
                    'Please set Account Payable before activating.'
                ))
            bank_account = rec.bank_journal_id.default_account_id
            if not bank_account:
                raise UserError(_(
                    'The selected bank journal has no default account. '
                    'Please configure it in Accounting > Journals.'
                ))
            partner = rec.bank_journal_id.bank_account_id.partner_id \
                if rec.bank_journal_id.bank_account_id \
                else self.env.company.partner_id
            move_vals = {
                'journal_id': rec.bank_journal_id.id,
                'date': rec.start_date or fields.Date.context_today(self),
                'ref': _('Pre-Shipment Loan Disbursement: %s') % rec.name,
                'preshipment_loan_id': rec.id,
                'move_type': 'entry',
                'line_ids': [
                    (0, 0, {
                        'name': _('Loan Received: %s') % rec.name,
                        'account_id': bank_account.id,
                        'debit': rec.loan_amount,
                        'credit': 0.0,
                    }),
                    (0, 0, {
                        'name': _('Loan Payable: %s') % rec.name,
                        'account_id': rec.account_payable_id.id,
                        'partner_id': partner.id,
                        'debit': 0.0,
                        'credit': rec.loan_amount,
                    }),
                ],
            }
            self.env['account.move'].create(move_vals)

    def action_create_bill(self):
        """Create a vendor bill for loan used + interest."""
        for rec in self:
            if not rec.expense_account_id:
                raise UserError(_('Please set the Expense Account before creating a bill.'))
            if rec.loan_used <= 0 and rec.total_interest <= 0:
                raise UserError(_('No loan usage or interest to bill.'))

            partner = rec.bank_journal_id.bank_account_id.partner_id \
                if rec.bank_journal_id.bank_account_id else False

            # Bills must use a purchase journal, not a bank journal
            purchase_journal = self.env['account.journal'].search([
                ('type', '=', 'purchase'),
                ('company_id', '=', rec.company_id.id),
            ], limit=1)
            if not purchase_journal:
                raise UserError(_('No purchase journal found. Please create one in Accounting > Configuration > Journals.'))

            bill_lines = []
            if rec.loan_used > 0:
                bill_lines.append((0, 0, {
                    'name': _('Loan Usage: %s') % rec.name,
                    'account_id': rec.account_payable_id.id if rec.account_payable_id else rec.expense_account_id.id,
                    'quantity': 1,
                    'price_unit': rec.loan_used,
                }))
            if rec.total_interest > 0:
                bill_lines.append((0, 0, {
                    'name': _('Loan Interest: %s') % rec.name,
                    'account_id': rec.expense_account_id.id,
                    'quantity': 1,
                    'price_unit': rec.total_interest,
                }))
            if rec.penalty_amount > 0:
                bill_lines.append((0, 0, {
                    'name': _('Penalty: %s') % rec.name,
                    'account_id': rec.expense_account_id.id,
                    'quantity': 1,
                    'price_unit': rec.penalty_amount,
                }))

            bill_vals = {
                'move_type': 'in_invoice',
                'journal_id': purchase_journal.id,
                'partner_id': partner.id if partner else False,
                'ref': _('Pre-Shipment Loan Bill: %s') % rec.name,
                'invoice_date': fields.Date.context_today(self),
                'preshipment_loan_id': rec.id,
                'invoice_line_ids': bill_lines,
            }
            self.env['account.move'].create(bill_vals)

    # -------------------------------------------------------------------------
    # SMART BUTTON ACTIONS
    # -------------------------------------------------------------------------
    def action_view_moves(self):
        self.ensure_one()
        moves = self.env['account.move'].search([
            ('preshipment_loan_id', '=', self.id),
            ('move_type', '=', 'entry'),
        ])
        return {
            'type': 'ir.actions.act_window',
            'name': _('Journal Entries'),
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', moves.ids)],
        }

    def action_view_bills(self):
        self.ensure_one()
        bills = self.env['account.move'].search([
            ('preshipment_loan_id', '=', self.id),
            ('move_type', '=', 'in_invoice'),
        ])
        return {
            'type': 'ir.actions.act_window',
            'name': _('Bills'),
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', bills.ids)],
        }

    def action_view_sale_orders(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Sales Orders'),
            'res_model': 'sale.order',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.sale_order_ids.ids)],
        }