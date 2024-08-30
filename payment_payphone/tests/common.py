import json

from requests import PreparedRequest, Response, Session
from werkzeug import urls

from odoo.addons.payment.tests.common import PaymentCommon
from odoo.addons.payment_payphone.models.payment_provider import PAYPHONE_URL

PAYPHONE_DUMMY_ID = "DUMMY_ID"


class PayphoneCommon(PaymentCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.amount = 10
        cls.currency = cls.currency_usd
        cls.provider = cls._prepare_provider(
            "payphone",
            update_values={
                "payphone_access_token": "DUMMY_ACCESS_TOKEN",
            },
        )
        cls.init_transaction_vals = {
            "paymentId": PAYPHONE_DUMMY_ID,
            "payWithPayPhone": urls.url_join(
                PAYPHONE_URL, f"PayPhone/Index?paymentId={PAYPHONE_DUMMY_ID}"
            ),
        }
        cls.payphone_wrong_account = {
            "message": "Su aplicación no esta autorizada para acceder a este recurso",
        }
        cls.payphone_result = {
            "id": PAYPHONE_DUMMY_ID,
            "clientTransactionId": cls.reference,
        }
        cls.payphone_result_cancel = dict(cls.payphone_result, id="0")
        cls.payphone_transaction = {
            "email": "test@example.com",
            "cardType": "Test",
            "bin": "777300",
            "lastDigits": "2632",
            "deferredCode": "00000000",
            "deferred": False,
            "cardBrand": "PayPhone PayPhone",
            "amount": 10,
            "clientTransactionId": PAYPHONE_DUMMY_ID,
            "phoneNumber": "593123456789",
            "statusCode": 3,
            "transactionStatus": "Approved",
            "authorizationCode": "W23801042",
            "messageCode": 0,
        }
        # statusCode: 3 = OK, 2 = Cancel, else: Error
        cls.payphone_transaction_ok = dict(cls.payphone_transaction)
        cls.payphone_transaction_rejected = dict(cls.payphone_transaction, statusCode=2)
        cls.payphone_transaction_error = dict(cls.payphone_transaction, statusCode=4)

    @classmethod
    def _request_handler(cls, s: Session, res: PreparedRequest, /, **kw):
        # Payphone transaction init, set default values
        if res.url.startswith(PAYPHONE_URL) and "button/Prepare" in res.url:
            return cls._make_payphone_requests(res.url, cls.init_transaction_vals)
        return super()._request_handler(s, res, **kw)

    @classmethod
    def _make_payphone_requests(cls, url, json_data=None, status_code=200):
        """
        :param json_data: dict to response
        :param status_code:
        :returns response: requests response"""
        json_content = json_data or {}
        response = Response()
        response.status_code = status_code
        response._content = json.dumps(json_content).encode()
        response.url = url
        response.headers["Content-Type"] = "application/json"
        return response
