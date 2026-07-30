from odoo import models, fields, api, _
from odoo.exceptions import UserError

class OverdraftCloseWizard(models.TransientModel):
    _name = 'overdraft.close.wizard'
    _description = 'Double Warning Wizard to Close Overdraft'

    overdraft_id = fields.Many2one('overdraft.interest', string='Overdraft', required=True)
    step = fields.Selection([('1', 'First Warning'), ('2', 'Final Warning')], default='1')

    def action_next_step(self):
        self.step = '2'
        return {
            'type': 'ir.actions.act_window',
            'name': _('Final Warning: Close Overdraft'),
            'res_model': 'overdraft.close.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_confirm_close(self):
        od = self.overdraft_id
        if od.outstanding_interest > 0 or od.outstanding_penalty > 0:
            raise UserError(_(
                'Cannot close: outstanding interest of %s and penalty of %s remain. '
                'Please settle all outstanding amounts before closing.'
            ) % (od.outstanding_interest, od.outstanding_penalty))
        od.write({'state': 'closed'})
        return {'type': 'ir.actions.act_window_close'}
