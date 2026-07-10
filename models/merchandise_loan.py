import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from datetime import date as dt_date

_logger = logging.getLogger(__name__)


class MerchandiseLoan(models.Model):
    _name = 'merchandise.loan'
    _description = 'Merchandise Loan'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_from desc, id desc'

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
        ('active', 'Active'),
        ('closed', 'Closed'),
    ], string='Status', default='draft', tracking=True, copy=False)

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
    # FIELDS — Period and Currency
    # -------------------------------------------------------------------------
    date_from = fields.Date(
        string='Start Date',
        default=fields.Date.context_today,
        required=True,
        tracking=True,
    )
    date_to = fields.Date(
        string='End Date',
        required=True,
        tracking=True,
    )
    activation_date = fields.Date(
        string='Activation Date',
        readonly=True,
        copy=False,
        help='Date when the loan was activated. Interest accrues from this date.',
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=_default_currency,
        required=True,
    )

    # -------------------------------------------------------------------------
    # FIELDS — Goods / Merchandise
    # -------------------------------------------------------------------------
    product_id = fields.Many2one(
        'product.product',
        string='Merchandise / Goods',
        required=True,
        tracking=True,
        help='The type of goods being financed',
    )
    goods_quantity = fields.Float(
        string='Total Goods Quantity',
        required=True,
        digits=(16, 3),
        tracking=True,
    )
    goods_unit_price = fields.Monetary(
        string='Unit Price',
        currency_field='currency_id',
        required=True,
        tracking=True,
    )
    total_goods_value = fields.Monetary(
        string='Total Goods Value',
        compute='_compute_goods_value',
        store=True,
        currency_field='currency_id',
    )
    warehouse_id = fields.Many2one(
        'stock.warehouse',
        string='Storage Warehouse',
        required=True,
        tracking=True,
        help='Warehouse where goods are stored under bank control',
    )

    # -------------------------------------------------------------------------
    # FIELDS — Loan Coverage (Company pays X% to bank, bank lends Y%)
    # -------------------------------------------------------------------------
    company_coverage_percent = fields.Float(
        string='Company Deposit (%)',
        default=30.0,
        required=True,
        digits=(5, 2),
        tracking=True,
        help='Percentage the company pays to the bank upfront (e.g. 30)',
    )
    bank_coverage_percent = fields.Float(
        string='Bank Loan (%)',
        compute='_compute_goods_value',
        store=True,
        digits=(5, 2),
        readonly=True,
    )
    company_amount = fields.Monetary(
        string='Company Deposit Amount',
        compute='_compute_goods_value',
        store=True,
        currency_field='currency_id',
    )
    bank_amount = fields.Monetary(
        string='Bank Loan Amount',
        compute='_compute_goods_value',
        store=True,
        currency_field='currency_id',
        help='Amount the bank lends — this is the loan to repay',
    )

    # -------------------------------------------------------------------------
    # FIELDS — Interest Rates
    # -------------------------------------------------------------------------
    annual_interest_rate = fields.Float(
        string='Annual Interest Rate (%)',
        digits=(16, 6),
        required=True,
        tracking=True,
        help='Annual interest rate as a percentage (e.g. 16.5)',
    )

    # -------------------------------------------------------------------------
    # FIELDS — Purpose & Collateral
    # -------------------------------------------------------------------------
    purpose = fields.Text(
        string='Purpose',
        tracking=True,
        help='Intended use of this merchandise loan (e.g. import of plastic raw materials, vehicle acquisition).',
    )
    collateral_document_ids = fields.Many2many(
        'ir.attachment',
        'merchandise_loan_collateral_attachment_rel',
        'loan_id',
        'attachment_id',
        string='Collateral Documents',
        help='Attach collateral documents such as import invoices, warehouse receipts, or guarantees.',
    )

    # -------------------------------------------------------------------------
    # FIELDS — Computed Totals
    # -------------------------------------------------------------------------
    total_paid = fields.Monetary(
        string='Total Paid',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
    )
    total_goods_released_qty = fields.Float(
        string='Total Goods Released (Qty)',
        compute='_compute_totals',
        store=True,
        digits=(16, 3),
    )
    goods_held_qty = fields.Float(
        string='Goods Held by Bank (Qty)',
        compute='_compute_totals',
        store=True,
        digits=(16, 3),
    )
    total_interest = fields.Monetary(
        string='Total Interest Accrued',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
    )
    outstanding_loan = fields.Monetary(
        string='Outstanding Loan',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
    )
    interest_per_unit = fields.Monetary(
        string='Interest per Unit',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
        help='Total interest accrued ÷ total goods quantity',
    )
    actual_unit_cost = fields.Monetary(
        string='Actual Cost per Unit',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
        help='Unit price + interest per unit',
    )

    # -------------------------------------------------------------------------
    # FIELDS — Payment Lines
    # -------------------------------------------------------------------------
    loan_line_ids = fields.One2many(
        'merchandise.loan.line',
        'loan_id',
        string='Goods Release Entries',
    )

    # -------------------------------------------------------------------------
    # FIELDS — Accounting Links
    # -------------------------------------------------------------------------
    move_ids = fields.One2many(
        'account.move', 'merchandise_loan_id',
        string='Journal Entries',
    )
    bill_ids = fields.One2many(
        'account.move', 'merchandise_loan_id',
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
                ('merchandise_loan_id', '=', rec.id),
            ])
            rec.move_count = len(moves.filtered(lambda m: m.move_type == 'entry'))
            rec.bill_count = len(moves.filtered(lambda m: m.move_type == 'in_invoice'))

    @api.depends('goods_quantity', 'goods_unit_price', 'company_coverage_percent')
    def _compute_goods_value(self):
        for rec in self:
            total = rec.goods_quantity * rec.goods_unit_price
            rec.total_goods_value = total
            rec.bank_coverage_percent = 100.0 - rec.company_coverage_percent
            rec.company_amount = round(total * rec.company_coverage_percent / 100.0, 2)
            rec.bank_amount = round(total * rec.bank_coverage_percent / 100.0, 2)

    @api.depends(
        'loan_line_ids.payment_amount',
        'loan_line_ids.goods_released_quantity',
        'loan_line_ids.interest',
        'goods_quantity',
        'goods_unit_price',
        'bank_amount',
    )
    def _compute_totals(self):
        for rec in self:
            lines = rec.loan_line_ids
            rec.total_paid = sum(l.payment_amount for l in lines)
            rec.total_goods_released_qty = sum(l.goods_released_quantity for l in lines)
            rec.total_interest = sum(l.interest for l in lines)

            # Outstanding = bank loan - principal portion paid (total_paid - total_interest)
            principal_paid = rec.total_paid - rec.total_interest
            rec.outstanding_loan = max(rec.bank_amount - principal_paid, 0.0)

            # Goods still held
            rec.goods_held_qty = max(rec.goods_quantity - rec.total_goods_released_qty, 0.0)

            # Interest per unit
            if rec.goods_quantity:
                rec.interest_per_unit = round(rec.total_interest / rec.goods_quantity, 2)
            else:
                rec.interest_per_unit = 0.0

            # Actual cost per unit
            rec.actual_unit_cost = rec.goods_unit_price + rec.interest_per_unit

    # -------------------------------------------------------------------------
    # HELPER — Recalculate interest on all lines
    # -------------------------------------------------------------------------
    def _recalculate_line_interest(self):
        """Recalculate daily interest on every line based on outstanding balance
        and days elapsed since the previous entry (or activation date)."""
        for rec in self:
            if not rec.activation_date:
                continue
            daily_rate = rec.annual_interest_rate / 100.0 / 365.0
            sorted_lines = rec.loan_line_ids.sorted('date')
            prev_date = rec.activation_date
            outstanding = rec.bank_amount
            for line in sorted_lines:
                days = (line.date - prev_date).days if line.date else 0
                days = max(days, 0)
                interest = round(outstanding * daily_rate * days, 2)
                principal = line.goods_released_quantity * rec.goods_unit_price
                payment = round(principal + interest, 2)
                line.write({
                    'interest': interest,
                    'payment_amount': payment,
                })
                outstanding = max(outstanding - principal, 0.0)
                prev_date = line.date

    # -------------------------------------------------------------------------
    # SEQUENCE
    # -------------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('merchandise.loan') or 'New'
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

    def action_activate(self):
        """Activate the loan — sets activation date, interest accrues from here."""
        for rec in self:
            if rec.state != 'approved':
                raise UserError(_('Only approved loans can be activated.'))
            rec.activation_date = fields.Date.context_today(self)
            # Create disbursement journal entry
            rec._create_disbursement_journal_entry()
            rec.state = 'active'

    def action_reject(self):
        for rec in self:
            if rec.state != 'submitted':
                raise UserError(_('Only submitted records can be rejected.'))
            rec.state = 'draft'

    def action_close(self):
        for rec in self:
            if rec.state != 'active':
                raise UserError(_('Only active loans can be closed.'))
            rec.state = 'closed'

    def action_reset_to_draft(self):
        for rec in self:
            rec.state = 'draft'
            rec.activation_date = False

    # -------------------------------------------------------------------------
    # ACCOUNTING METHODS
    # -------------------------------------------------------------------------
    def _create_disbursement_journal_entry(self):
        """Create a journal entry for merchandise loan disbursement."""
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
            move_vals = {
                'journal_id': rec.bank_journal_id.id,
                'date': rec.activation_date or fields.Date.context_today(self),
                'ref': _('Merchandise Loan Disbursement: %s') % rec.name,
                'merchandise_loan_id': rec.id,
                'move_type': 'entry',
                'line_ids': [
                    (0, 0, {
                        'name': _('Loan Received: %s') % rec.name,
                        'account_id': bank_account.id,
                        'debit': rec.bank_amount,
                        'credit': 0.0,
                    }),
                    (0, 0, {
                        'name': _('Loan Payable: %s') % rec.name,
                        'account_id': rec.account_payable_id.id,
                        'debit': 0.0,
                        'credit': rec.bank_amount,
                    }),
                ],
            }
            self.env['account.move'].create(move_vals)

    def action_create_bill(self):
        """Create a vendor bill for outstanding amount + interest."""
        for rec in self:
            if not rec.expense_account_id or not rec.account_payable_id:
                raise UserError(_(
                    'Please set both Expense Account and Account Payable.'
                ))
            if rec.outstanding_loan <= 0 and rec.total_interest <= 0:
                raise UserError(_('No outstanding amount to bill.'))

            partner = rec.bank_journal_id.bank_account_id.partner_id \
                if rec.bank_journal_id.bank_account_id else False

            # Bills must use a purchase journal, not a bank journal
            purchase_journal = self.env['account.journal'].search([
                ('type', '=', 'purchase'),
                ('company_id', '=', self.env.company.id),
            ], limit=1)
            if not purchase_journal:
                raise UserError(_('No purchase journal found. Please create one in Accounting > Configuration > Journals.'))

            bill_lines = []
            if rec.outstanding_loan > 0:
                bill_lines.append((0, 0, {
                    'name': _('Merchandise Loan Principal: %s') % rec.name,
                    'account_id': rec.account_payable_id.id,
                    'quantity': 1,
                    'price_unit': rec.outstanding_loan,
                }))
            if rec.total_interest > 0:
                bill_lines.append((0, 0, {
                    'name': _('Merchandise Loan Interest: %s') % rec.name,
                    'account_id': rec.expense_account_id.id,
                    'quantity': 1,
                    'price_unit': rec.total_interest,
                }))

            bill_vals = {
                'move_type': 'in_invoice',
                'journal_id': purchase_journal.id,
                'partner_id': partner.id if partner else False,
                'ref': _('Merchandise Loan Bill: %s') % rec.name,
                'invoice_date': fields.Date.context_today(self),
                'merchandise_loan_id': rec.id,
                'invoice_line_ids': bill_lines,
            }
            self.env['account.move'].create(bill_vals)

    # -------------------------------------------------------------------------
    # SMART BUTTON ACTIONS
    # -------------------------------------------------------------------------
    def action_view_moves(self):
        self.ensure_one()
        moves = self.env['account.move'].search([
            ('merchandise_loan_id', '=', self.id),
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
            ('merchandise_loan_id', '=', self.id),
            ('move_type', '=', 'in_invoice'),
        ])
        return {
            'type': 'ir.actions.act_window',
            'name': _('Bills'),
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', bills.ids)],
        }
