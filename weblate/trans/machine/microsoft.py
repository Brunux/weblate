# -*- coding: utf-8 -*-
#
# Copyright © 2012 - 2017 Michal Čihař <michal@cihar.com>
#
# This file is part of Weblate <https://weblate.org/>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#

from __future__ import unicode_literals

from uuid import uuid4
from datetime import timedelta

from six.moves.urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

from django.conf import settings
from django.utils import timezone
from django.template.loader import get_template

from weblate.trans.machine.base import (
    MachineTranslation, MachineTranslationError, MissingConfiguration
)
from weblate.lang.data import DEFAULT_LANGS

COGNITIVE_BASE_URL = 'https://api.cognitive.microsoft.com/sts/v1.0'
COGNITIVE_TOKEN = COGNITIVE_BASE_URL + '/issueToken?Subscription-Key={0}'

BASE_URL = 'https://api.microsofttranslator.com/V2/Ajax.svc/'
TRANSLATE_URL = BASE_URL + 'Translate'
LIST_URL = BASE_URL + 'GetLanguagesForTranslate'
TOKEN_EXPIRY = timedelta(minutes=9)


class MicrosoftTranslation(MachineTranslation):
    """Microsoft Translator machine translation support."""
    name = 'Microsoft Translator'

    def __init__(self):
        """Check configuration."""
        super(MicrosoftTranslation, self).__init__()
        self._access_token = None
        self._token_expiry = None
        if not self.ms_supported():
            raise MissingConfiguration(
                'Microsoft Translator requires credentials'
            )

    def ms_supported(self):
        """Check whether service is supported."""
        return (
            settings.MT_MICROSOFT_ID is not None and
            settings.MT_MICROSOFT_SECRET is not None
        )

    def is_token_expired(self):
        """Check whether token is about to expire."""
        return self._token_expiry <= timezone.now()

    @property
    def access_token(self):
        """Obtain and caches access token."""
        if self._access_token is None or self.is_token_expired():
            data = self.json_req(
                'https://datamarket.accesscontrol.windows.net/v2/OAuth2-13',
                skip_auth=True,
                http_post=True,
                client_id=settings.MT_MICROSOFT_ID,
                client_secret=settings.MT_MICROSOFT_SECRET,
                scope='https://api.microsofttranslator.com',
                grant_type='client_credentials',
            )

            if 'error' in data:
                raise MachineTranslationError(
                    data.get('error', 'Unknown Error') +
                    data.get('error_description', 'No Error Description')
                )

            self._access_token = data['access_token']
            self._token_expiry = timezone.now() + TOKEN_EXPIRY

        return self._access_token

    def authenticate(self, request):
        """Hook for backends to allow add authentication headers to request."""
        request.add_header(
            'Authorization',
            'Bearer {0}'.format(self.access_token)
        )

    def convert_language(self, language):
        """Convert language to service specific code."""
        language = language.replace('_', '-').lower()
        if language == 'zh-tw':
            return 'zh-CHT'
        if language == 'zh-cn':
            return 'zh-CHS'
        if language == 'nb':
            return 'no'
        if language == 'pt-br':
            return 'pt'
        return language

    def download_languages(self):
        """Download list of supported languages from a service.

        Example of the response:
        ['af', 'ar', 'bs-Latn', 'bg', 'ca', 'zh-CHS', 'zh-CHT', 'yue', 'hr',
        'cs', 'da', 'nl', 'en', 'et', 'fj', 'fil', 'fi', 'fr', 'de', 'el',
        'ht', 'he', 'hi', 'mww', 'h', 'id', 'it', 'ja', 'sw', 'tlh',
        'tlh-Qaak', 'ko', 'lv', 'lt', 'mg', 'ms', 'mt', 'yua', 'no', 'otq',
        'fa', 'pl', 'pt', 'ro', 'r', 'sm', 'sr-Cyrl', 'sr-Latn', 'sk', 'sl',
        'es', 'sv', 'ty', 'th', 'to', 'tr', 'uk', 'ur', 'vi', 'cy']
        """
        return self.json_req(LIST_URL)

    def download_translations(self, source, language, text, unit, user):
        """Download list of possible translations from a service."""
        args = {
            'text': text[:5000],
            'from': source,
            'to': language,
            'contentType': 'text/plain',
            'category': 'general',
        }
        response = self.json_req(TRANSLATE_URL, **args)
        return [(response, 100, self.name, text)]


class MicrosoftCognitiveTranslation(MicrosoftTranslation):
    """Microsoft Cognitive Services Translator API support."""
    name = 'Microsoft Translator'

    LANGUAGE_CONVERTER = {
        'zh-hant': 'zh-CHT',
        'zh-hans': 'zh-CHS',
        'zh-tw': 'zh-CHT',
        'zh-cn': 'zh-CHS',
        'tlh-qaak': 'tlh-Qaak',
        'nb': 'no',
        'bs-latn': 'bs-Latn',
        'sr-latn': 'sr-Latn',
        'sr-cyrl': 'sr-Cyrl',
    }

    def ms_supported(self):
        """Check whether service is supported."""
        return settings.MT_MICROSOFT_COGNITIVE_KEY is not None

    @property
    def access_token(self):
        """Obtain and caches access token."""
        if self._access_token is None or self.is_token_expired():
            self._access_token = self.json_req(
                COGNITIVE_TOKEN.format(settings.MT_MICROSOFT_COGNITIVE_KEY),
                skip_auth=True,
                http_post=True,
                raw=True,
                fake='1',
            )
            self._token_expiry = timezone.now() + TOKEN_EXPIRY

        return self._access_token

    def convert_language(self, language):
        """Convert language to service specific code.

        Remove second part of locale in most of cases.
        """
        language = language.replace('_', '-').lower()
        if language in self.LANGUAGE_CONVERTER:
            return self.LANGUAGE_CONVERTER[language]
        return language.split('-')[0]


class MicrosoftTerminologyService(MachineTranslation):
    """
    The Microsoft Terminology Service API.

    Allows you to programmatically access the terminology,
    definitions and user interface (UI) strings available
    on the MS Language Portal through a web service (SOAP).
    """
    name = 'Microsoft Terminology'

    MS_TM_BASE = 'http://api.terminology.microsoft.com'
    MS_TM_API_URL = '{base}/Terminology.svc'.format(base=MS_TM_BASE)
    MS_TM_SOAP_XMLNS = '{base}/terminology'.format(base=MS_TM_BASE)
    MS_TM_SOAP_HEADER = '{xmlns}/Terminology/'.format(xmlns=MS_TM_SOAP_XMLNS)
    MS_TM_XPATH = './/{{{xmlns}}}'.format(xmlns=MS_TM_SOAP_XMLNS)

    def soap_req(self, url, http_post=False, skip_auth=False, **kwargs):
        soap_action = kwargs.get('soap_action', '')
        url = self.MS_TM_API_URL
        action = self.MS_TM_SOAP_HEADER + soap_action
        headers = {
            'SOAPAction': (
                '"{action}"'
            ).format(action=action),
            'Content-Type': 'text/xml; charset=utf-8'
        }
        if soap_action == 'GetLanguages':
            payload = {'xmlns': self.MS_TM_SOAP_XMLNS,
                       'soap_action': soap_action}
            template = get_template('trans/machine/microsoft_terminology_get_langs.jinja')
        elif soap_action == 'GetTranslations':
            source = kwargs.get('source', '')
            language = kwargs.get('language', '')
            text = kwargs.get('text', '')
            max_result = 5
            if soap_action and source and language and text:
                payload = {'action': action,
                           'url': url,
                           'xmlns': self.MS_TM_SOAP_XMLNS,
                           'uuid': uuid4(),
                           'text': text,
                           'from_lang': source,
                           'to_lang': language,
                           'max_result': max_result}
                template = get_template('trans/machine/microsoft_terminology_translate.jinja')
        else:
            raise MachineTranslationError(
                'Wrong SOAP request: "{soap_action}."').format(
                soap_action=soap_action)
        try:
            payload = template.render(payload)
            request = Request(url)
            request.timeout = 0.5
            for header, value in headers.iteritems():
                request.add_header(header, value)
            request.add_data(payload)
            handle = urlopen(request)
        except Exception as error:
            raise MachineTranslationError('{err}'.format(err=error))
        return handle

    def json_req(self, url, http_post=False, skip_auth=False, raw=False,
                 **kwargs):
        """Adapter to soap_req"""

        response = self.soap_req(
            url, http_post=False, skip_auth=True, raw=True, **kwargs)

        return response

    def soap_status_req(self, url, http_post=False, skip_auth=False, **kwargs):
        """Perform SOAP request with checking response status."""
        # Perform request
        response = self.soap_req(url, http_post, skip_auth, **kwargs)

        if response.code != 200:
            raise MachineTranslationError(response.msg)

        return response

    def json_status_req(self, url, http_post=False, skip_auth=False, **kwargs):
        """Perform SOAP request with checking response status."""
        # Perform request
        response = self.soap_status_req(url,
                                        http_post,
                                        skip_auth=True,
                                        **kwargs)

        if response.code != 200:
            raise MachineTranslationError(response.msg)

        return response

    def download_languages(self):
        """Get list of supported languages."""
        soap_action = 'GetLanguages'
        soap_target = 'GetLanguagesResult'
        soap_target_envelop = 'Code'
        languages = []
        xpath = self.MS_TM_XPATH
        resp = self.soap_status_req(self.MS_TM_API_URL,
                                    soap_action=soap_action)
        root = ET.fromstring(resp.read())
        results = root.find(xpath + soap_target)
        if results is not None:
            for lang in results:
                languages.append(lang.find(xpath + soap_target_envelop).text)
        return languages

    def download_translations(self, source, language, text, unit, user):
        """Download list of possible translations from the service."""
        soap_action = 'GetTranslations'
        soap_target = 'GetTranslationsResult'
        soap_target_translated = 'TranslatedText'
        soap_target_confidence = 'ConfidenceLevel'
        soap_target_original = 'OriginalText'
        translations = []
        xpath = self.MS_TM_XPATH
        resp = self.soap_status_req(self.MS_TM_API_URL,
                                    soap_action=soap_action,
                                    source=source,
                                    language=language,
                                    text=text)
        root = ET.fromstring(resp.read())
        results = root.find(xpath + soap_target)
        if results is not None:
            for translation in results:
                translations.append(tuple([
                    translation.find(xpath + soap_target_translated).text,
                    int(translation.find(xpath + soap_target_confidence).text),
                    self.name,
                    translation.find(xpath + soap_target_original).text
                ]))
        return translations

    def translate(self, language, text, unit, user):
        """Return list of machine translations."""
        if text == '':
            return []

        language = self.convert_language(language)
        source = self.convert_language(
            unit.translation.subproject.project.source_language.code
        )
        if not self.is_supported(source, language):
            # Try adding country code from DEFAULT_LANGS
            if '-' not in language or '_' not in language:
                for lang in DEFAULT_LANGS:
                    if lang.split('_')[0] == language:
                        language = lang.replace('_', '-').lower()
                        break
            if '-' not in source or '_' not in source:
                for lang in DEFAULT_LANGS:
                    if lang.split('_')[0] == source:
                        source = lang.replace('_', '-').lower()
                        break
            if source == language:
                return []
            if not self.is_supported(source, language):
                return []
        try:
            translations = self.download_translations(
                source, language, text, unit, user
            )
            return [
                {
                    'text': trans[0],
                    'quality': trans[1],
                    'service': trans[2],
                    'source': trans[3]
                }
                for trans in translations
            ]
        except Exception as exc:
            self.report_error(
                exc,
                'Failed to fetch translations from %s',
            )
            raise MachineTranslationError('{0}: {1}'.format(
                exc.__class__.__name__,
                str(exc)
            ))
