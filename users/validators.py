import re
from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

class UppercaseValidator:
    def validate(self, password, user=None):
        if not re.findall('[A-Z]', password):
            raise ValidationError(
                _("Password harus mengandung setidaknya satu huruf besar (A-Z)."),
                code='password_no_upper',
            )

    def get_help_text(self):
        return _("Password harus mengandung setidaknya satu huruf besar (A-Z).")

class SpecialCharacterValidator:
    def validate(self, password, user=None):
        if not re.findall('[^A-Za-z0-9]', password):
            raise ValidationError(
                _("Password harus mengandung setidaknya satu karakter spesial (contoh: @, #, $)."),
                code='password_no_symbol',
            )

    def get_help_text(self):
        return _("Password harus mengandung setidaknya satu karakter spesial (contoh: @, #, $).")