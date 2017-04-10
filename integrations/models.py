from __future__ import unicode_literals

from django.db import models

# Create your models here.
class OAuthToken(models.Model):
    token = models.CharField(max_length=64)
