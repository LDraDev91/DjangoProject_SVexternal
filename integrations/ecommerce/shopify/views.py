from django.shortcuts import render
from django.views.generic import FormView
from integrations.forms import ShopifyForm, ShopifyCallbackForm
from .client import ShopifyClient
from django.shortcuts import redirect
import uuid

# Create your views here.
class StartShopifyView(FormView):
    template_name = 'integrations/shopify_start.html'
    form_class = ShopifyForm

    def form_valid(self, form):
        nonce = str(uuid.uuid4())

        # Shopify requires us to check the nonce to make sure it's coming from us so store it in the session.
        self.request.session['shopify_nonce'] = nonce

        client = ShopifyClient(shop="%s.myshopify.com"%form.cleaned_data['shop'])

        # Send the user to shopify to authorize if the form is valid
        return redirect(client.get_authorize_url(nonce))

class ShopifyCallbackView(FormView):
    form_class = ShopifyCallbackForm
    template_name = 'integrations/shopify_callback.html'

    def get_context_data(self, **kwargs):
        data = super(ShopifyCallbackView, self ).get_context_data(**kwargs)

        if self.request.GET.get('state') == self.request.session.get('shopify_nonce'):
            client = ShopifyClient(shop=self.request.GET.get('shop'))
            if client.validate_params(self.request.GET):
                client.request_token(self.request.GET)
                data['client'] = client
            else:
                data['error'] = 'Invalid request from shopify. Did not pass hmac validation.'
        else:
            data['error'] = 'Invalid nonce from Shopify'

        return data
