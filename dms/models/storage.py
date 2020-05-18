# Copyright 2020 RGB Consulting
# Copyright 2017-2019 MuK IT GmbH
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import logging

from odoo import _, api, fields, models
from odoo.exceptions import AccessError

_logger = logging.getLogger(__name__)


class Storage(models.Model):
    _name = "dms.storage"
    _description = "Storage"

    name = fields.Char(string="Name", required=True)
    save_type = fields.Selection(
        selection=[("database", "Database")],
        string="Save Type",
        default="database",
        required=True,
        help="The save type is used to determine how a file is saved bythe "
        "system. If you change this setting, you can migrate existing "
        "files manually by triggering the action.",
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        default=lambda self: self.env.user.company_id,
        help="If set, directories and files will only be available for "
        "the selected company.",
    )
    is_hidden = fields.Boolean(
        string="Storage is Hidden",
        default=False,
        help="Indicates if directories and files are hidden by default.",
    )
    root_directory_ids = fields.One2many(
        comodel_name="dms.directory",
        inverse_name="root_storage_id",
        string="Root Directories",
        copy=False,
    )
    storage_directory_ids = fields.One2many(
        comodel_name="dms.directory",
        inverse_name="storage_id",
        string="Directories",
        readonly=True,
        copy=False,
    )
    storage_file_ids = fields.One2many(
        comodel_name="dms.file",
        inverse_name="storage_id",
        string="Files",
        readonly=True,
        copy=False,
    )
    count_storage_directories = fields.Integer(
        compute="_compute_count_storage_directories", string="Count Directories"
    )
    count_storage_files = fields.Integer(
        compute="_compute_count_storage_files", string="Count Files"
    )

    def action_storage_migrate(self):
        if not self.env.user.has_group("dms.group_dms_manager"):
            raise AccessError(_("Only managers can execute this action."))
        files = self.env["dms.file"].with_context(active_test=False).sudo()
        for record in self:
            domain = ["&", ("content_binary", "=", False), ("storage", "=", record.id)]
            files |= files.search(domain)
        files.action_migrate()

    def action_save_onboarding_storage_step(self):
        self.env.user.company_id.set_onboarding_step_done(
            "documents_onboarding_storage_state"
        )

    @api.depends("storage_directories")
    def _compute_count_storage_directories(self):
        for rec in self:
            rec.count_storage_directories = len(rec.storage_directories)

    @api.depends("storage_files")
    def _compute_count_storage_files(self):
        for rec in self:
            rec.count_storage_files = len(rec.storage_files)
