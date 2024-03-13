from unittest.mock import patch

import requests

from odoo import _
from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.payment.tests.http_common import PaymentHttpCommon
from odoo.addons.payment_payphone.controllers.main import PayphoneController
from odoo.addons.payment_payphone.tests.common import PayphoneCommon


@tagged("post_install", "-at_install")
class TestPaymentTransaction(PayphoneCommon, PaymentHttpCommon):
    @mute_logger("odoo.addons.payment.models.payment_transaction")
    def test_01_redirect_form_values(self):
        tx = self._create_transaction(flow="redirect")
        processing_values = tx._get_processing_values()
        form_info = self._extract_values_from_html_form(
            processing_values["redirect_form_html"]
        )
        self.assertEqual(
            form_info["action"], self.init_transaction_vals["payWithPayPhone"]
        )
        self.assertEqual(form_info["method"], "get")
        self.assertEqual(
            form_info["inputs"].get("paymentId"),
            self.init_transaction_vals["paymentId"],
        )

    @mute_logger("odoo.addons.payment.models.payment_transaction")
    def test_01_transaction_error_account(self):
        _origin_post = requests.post

        def _patch_get_payphone(url, *args, **kwargs):
            if "button/Prepare" in url:
                return PayphoneCommon._make_payphone_requests(
                    url, self.payphone_wrong_account, status_code=401
                )
            return _origin_post(url, *args, **kwargs)

        tx = self._create_transaction(flow="redirect")
        with patch.object(requests, "post", _patch_get_payphone):
            with self.assertRaises(ValidationError), self.assertLogs(
                level="ERROR"
            ) as log_catcher:
                tx._get_processing_values()
                self.assertEqual(
                    len(log_catcher.output), 1, "Exactly one warning should be logged"
                )
                self.assertIn("Invalid API request", log_catcher.output[0])

    @mute_logger("odoo.addons.payment.models.payment_transaction")
    def test_02_feedback_done(self):
        _origin_post = requests.post

        def _patch_get_payphone(url, *args, **kwargs):
            if "button/V2/Confirm" in url:
                return PayphoneCommon._make_payphone_requests(
                    url, self.payphone_transaction_ok
                )
            return _origin_post(url, *args, **kwargs)

        tx = self._create_transaction(flow="redirect")
        tx._get_processing_values()
        with patch.object(requests, "post", _patch_get_payphone):
            tx._handle_notification_data(tx.provider_code, self.payphone_result)
        self.assertEqual(tx.state, "done")

    @mute_logger("odoo.addons.payment.models.payment_transaction")
    def test_03_feedback_rejected(self):
        _origin_post = requests.post

        def _patch_get_payphone(url, *args, **kwargs):
            if "button/V2/Confirm" in url:
                return PayphoneCommon._make_payphone_requests(
                    url, self.payphone_transaction_rejected
                )
            return _origin_post(url, *args, **kwargs)

        tx = self._create_transaction(flow="redirect")
        tx._get_processing_values()
        with patch.object(requests, "post", _patch_get_payphone):
            tx._handle_notification_data(
                tx.provider_code, self.payphone_transaction_rejected
            )
        self.assertEqual(tx.state, "cancel")

    @mute_logger("odoo.addons.payment.models.payment_transaction")
    def test_04_feedback_cancel(self):
        tx = self._create_transaction(flow="redirect")
        tx._get_processing_values()
        tx._handle_notification_data(tx.provider_code, self.payphone_result_cancel)
        self.assertEqual(tx.state, "cancel")

    @mute_logger("odoo.addons.payment.models.payment_transaction")
    def test_05_feedback_error(self):
        _origin_post = requests.post

        def _patch_get_payphone(url, *args, **kwargs):
            if "button/V2/Confirm" in url:
                return PayphoneCommon._make_payphone_requests(
                    url, self.payphone_transaction_error
                )
            return _origin_post(url, *args, **kwargs)

        tx = self._create_transaction(flow="redirect")
        tx._get_processing_values()
        with patch.object(requests, "post", _patch_get_payphone):
            tx._handle_notification_data(
                tx.provider_code, self.payphone_transaction_error
            )
        self.assertEqual(tx.state, "error")

    @mute_logger("odoo.addons.payment.models.payment_transaction")
    def test_06_provider_none(self):
        self.provider = self.dummy_provider
        tx = self._create_transaction(flow="redirect")
        tx._get_processing_values()
        tx._handle_notification_data(tx.provider_code, {})
        # en provider none no se ejecutara codigo, asi que deberia seguir en draft
        self.assertEqual(tx.state, "draft")

    @mute_logger("odoo.addons.payment.models.payment_transaction")
    def test_07_transaction_from_controller_ok(self):
        _origin_post = requests.post

        def _patch_get_payphone(url, *args, **kwargs):
            if "button/V2/Confirm" in url:
                return PayphoneCommon._make_payphone_requests(
                    url, self.payphone_transaction_ok
                )
            return _origin_post(url, *args, **kwargs)

        return_url = self._build_url(PayphoneController._return_url)
        tx = self._create_transaction(flow="redirect")
        tx._get_processing_values()
        with patch.object(requests, "post", _patch_get_payphone):
            controller_response = self._make_http_get_request(
                return_url, params=self.payphone_result
            )
        self.assertEqual(controller_response.status_code, 200)
        self.assertEqual(tx.state, "done")
        self.assertTrue("/payment/status" in controller_response.url)

    @mute_logger("odoo.addons.payment.models.payment_transaction")
    def test_08_controller_wrong_client_transaction_id(self):
        return_url = self._build_url(PayphoneController._return_url)
        tx = self._create_transaction(flow="redirect")
        tx._get_processing_values()
        controller_response = self._make_http_get_request(
            return_url,
            params={},  # no clientTransactionId
        )
        self.assertEqual(controller_response.status_code, 400)
        text_expected = _("Payphone: Received data with missing reference.")
        self.assertIn(text_expected, controller_response.text)
        clientTransactionId = "WRONG"
        controller_response = self._make_http_get_request(
            return_url,
            params={"clientTransactionId": clientTransactionId},
        )
        self.assertEqual(controller_response.status_code, 400)
        text_expected = _(
            "Payphone: No transaction found matching reference %s.", clientTransactionId
        )
        self.assertIn(text_expected, controller_response.text)
