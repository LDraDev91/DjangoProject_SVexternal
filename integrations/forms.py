from django import forms

class ShopifyForm(forms.Form):
    shop = forms.CharField()

class ShopifyCallbackForm(forms.Form):
    code = forms.CharField()
    hmac = forms.CharField()
    shop = forms.CharField()
    state = forms.CharField()
    timestamp = forms.CharField()
