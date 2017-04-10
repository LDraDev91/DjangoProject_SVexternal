from integrations.client import APIClient
import urllib
import time
import hmac
from hashlib import sha256
import six
from django.conf import settings
import json
from .exceptions import ValidationException
import logging
logger = logging.getLogger(__name__)

class ShopifyClient(APIClient):
    API_KEY = '323613a5f7cde48498e36a5043482d77'
    SCOPES = 'read_orders,read_customers,read_draft_orders,read_shipping,read_products,write_products'
    REDIRECT_URI = 'http://localhost:8000/integrations/shopify/callback/'
    SECRET = '9db9eec77420f58a332c6da3b7f9033e'

    def __init__(self, *args, **kwargs):
        self.token = kwargs.get('token')
        self.shop = kwargs.get('shop')

    def request_token(self, params):
        if self.token is not None:
            return self.token

        if not self.validate_params(params):
            raise ValidationException('Invalid HMAC: Possibly malicious login')

        code = params['code']
        url = "https://%s/admin/oauth/access_token?" % self.shop
        logger.info("Url is: %s" % url)
        query_params = dict(client_id=self.API_KEY, client_secret=self.SECRET, code=code)
        logger.info("Query params; %s" % query_params)
        request = urllib.request.Request(url, urllib.parse.urlencode(query_params).encode('utf-8'))
        response = urllib.request.urlopen(request)
        logger.info(response)

        if response.code == 200:
            self.token = json.loads(response.read().decode('utf-8'))['access_token']
            return self.token
        else:
            raise Exception(response.msg)

    def get_authorize_url(self, nonce):
        params = {
            "client_id": self.API_KEY,
            "scope": self.SCOPES,
            "redirect_uri": self.REDIRECT_URI,
            "state": nonce,
        }

        qs = urllib.parse.urlencode(params, doseq=True)
        return "https://{0}/admin/oauth/authorize?".format(self.shop) + qs

    @classmethod
    def validate_params(cls, params):
        # Avoid replay attacks by making sure the request
        # isn't more than a day old.
        one_day = 24 * 60 * 60
        if int(params['timestamp']) < time.time() - one_day:
            return False

        return cls.validate_hmac(params)

    @classmethod
    def validate_hmac(cls, params):
        if 'hmac' not in params:
            return False

        hmac_calculated = cls.calculate_hmac(params).encode('utf-8')
        hmac_to_verify = params['hmac'].encode('utf-8')

        # Try to use compare_digest() to reduce vulnerability to timing attacks.
        # If it's not available, just fall back to regular string comparison.
        try:
            return hmac.compare_digest(hmac_calculated, hmac_to_verify)
        except AttributeError:
            return hmac_calculated == hmac_to_verify

    @classmethod
    def calculate_hmac(cls, params):
        """
        Calculate the HMAC of the given parameters in line with Shopify's rules for OAuth authentication.
        See http://docs.shopify.com/api/authentication/oauth#verification.
        """
        encoded_params = cls.__encoded_params_for_signature(params)
        # Generate the hex digest for the sorted parameters using the SECRET.
        return hmac.new(cls.SECRET.encode(), encoded_params.encode(), sha256).hexdigest()

    @classmethod
    def __encoded_params_for_signature(cls, params):
        """
        Sort and combine query parameters into a single string, excluding those that should be removed and joining with '&'
        """

        def encoded_pairs(params):
            for k, v in six.iteritems(params):
                if k != 'hmac':
                    # escape delimiters to avoid tampering
                    k = str(k).replace("%", "%25").replace("=", "%3D")
                    v = str(v).replace("%", "%25")
                    yield '{0}={1}'.format(k, v).replace("&", "%26")

        return "&".join(sorted(encoded_pairs(params)))
