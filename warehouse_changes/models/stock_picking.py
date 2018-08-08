import datetime
from odoo import api, exceptions, fields, models, _


class stock_picking_approval(models.Model):
    _inherit = 'stock.picking'

    state = fields.Selection([
        ('draft', 'Draft'), ('cancel', 'Cancelled'),
        ('waiting', 'Waiting Another Operation'),
        ('confirmed', 'Waiting Availability'),
        ('partially_available', 'Partially Available'),
        ('approved', 'Approved'),
        ('assigned', 'Available'), ('done', 'Done')], string='Status', compute='_compute_state',
        copy=False, index=True, readonly=True, store=True, track_visibility='onchange',
        help=" * Draft: not confirmed yet and will not be scheduled until confirmed\n"
             " * Waiting Another Operation: waiting for another move to proceed before it becomes automatically available (e.g. in Make-To-Order flows)\n"
             " * Waiting Availability: still waiting for the availability of products\n"
             " * Partially Available: some products are available and reserved\n"
             " * Ready to Transfer: products reserved, simply waiting for confirmation.\n"
             " * Transferred: has been processed, can't be modified or cancelled anymore\n"
             " * Cancelled: has been cancelled, can't be confirmed anymore")

    need_approval = fields.Boolean('Need Approval', compute='_get_picking_type')
    first_approved_by = fields.Many2one('res.users', string='First Approved')
    second_approved_by = fields.Many2one('res.users', string='Second Approved')

    @api.multi
    def _get_picking_type(self):
        for picking in self:
            if picking.picking_type_id.code == 'internal':
                picking.need_approval = False
            else:
                picking.need_approval = True

    @api.multi
    def action_approve(self):
        for order in self:
            order.write({'state': 'approved', 'first_approved_by': self._uid})
        return True

    @api.multi
    def do_new_transfer(self):
        res = super(stock_picking_approval, self).do_new_transfer()
        for rec in self:
            rec.write({'second_approved_by': self._uid})
        return res

    @api.depends('move_type', 'launch_pack_operations', 'move_lines.state', 'move_lines.picking_id',
                 'move_lines.partially_available')
    @api.one
    def _compute_state(self):
        ''' State of a picking depends on the state of its related stock.move
         - no moves: draft or assigned (launch_pack_operations)
         - all moves canceled: cancel
         - all moves done (including possible canceled): done
         - All at once picking: least of confirmed / waiting / assigned
         - Partial picking
          - all moves assigned: assigned
          - one of the move is assigned or partially available: partially available
          - otherwise in waiting or confirmed state
        '''
        if not self.move_lines and self.launch_pack_operations:
            self.state = 'assigned'
        elif not self.move_lines:
            self.state = 'draft'
        elif any(move.state == 'draft' for move in self.move_lines):  # TDE FIXME: should be all ?
            self.state = 'draft'
        elif all(move.state == 'cancel' for move in self.move_lines):
            self.state = 'cancel'
        elif all(move.state in ['cancel', 'done'] for move in self.move_lines):
            self.state = 'done'
        elif self.move_type == 'one':
            ordered_moves = self.move_lines.filtered(
                lambda move: move.state not in ['cancel', 'done']
            ).sorted(
                key=lambda move: (move.state == 'assigned' and 2) or (move.state == 'waiting' and 1) or 0, reverse=False
            )
            self.state = ordered_moves[0].state
        else:
            filtered_moves = self.move_lines.filtered(lambda move: move.state not in ['cancel', 'done'])
            if not all(move.state == 'assigned' for move in filtered_moves) and any(
                    move.state == 'assigned' for move in filtered_moves):
                self.state = 'partially_available'
            elif any(move.partially_available for move in filtered_moves):
                self.state = 'partially_available'
            else:
                ordered_moves = filtered_moves.sorted(
                    key=lambda move: (move.state == 'assigned' and 2) or (move.state == 'waiting' and 1) or 0,
                    reverse=True)
                self.state = ordered_moves[0].state
