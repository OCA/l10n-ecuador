import logging
import pprint

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class PayphoneController(http.Controller):
    _return_url = "/payment/payphone/return"

    @http.route(
        _return_url,
        type="http",
        methods=["GET"],
        auth="public",
        csrf=False,
        save_session=False,
    )
    def payphone_return_from_checkout(self, **data):
        """Process the notification data
        sent by Payphone after redirection from checkout.

        :param dict data: The notification data.
        """
        # Handle the notification data.
        _logger.debug(
            "Handling redirection from Payphone with data:\n%s", pprint.pformat(data)
        )
        request.env["payment.transaction"].sudo()._handle_notification_data(
            "payphone", data
        )
        return request.redirect("/payment/status")
