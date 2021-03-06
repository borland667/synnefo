# Copyright (C) 2010-2014 GRNET S.A.
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
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from functools import wraps
from time import time, mktime
import datetime

from django.http import HttpResponse
from django.utils import simplejson as json
from django.template.loader import render_to_string

from astakos.im.models import AstakosUser, Component
from snf_django.lib.api import faults
from snf_django.lib.api.utils import isoformat

from astakos.im.forms import FeedbackForm
from astakos.im.user_utils import send_feedback as send_feedback_func

import logging
logger = logging.getLogger(__name__)

absolute = lambda request, url: request.build_absolute_uri(url)


def _dthandler(obj):
    if isinstance(obj, datetime.datetime):
        return isoformat(obj)
    else:
        raise TypeError


def json_response(content, status_code=None):
    response = HttpResponse()
    if status_code is not None:
        response.status_code = status_code

    response.content = json.dumps(content, default=_dthandler)
    response['Content-Type'] = 'application/json; charset=UTF-8'
    response['Content-Length'] = len(response.content)
    return response


def xml_response(content, template, status_code=None):
    response = HttpResponse()
    if status_code is not None:
        response.status_code = status_code

    response.content = render_to_string(template, content)
    response['Content-Type'] = 'application/xml; charset=UTF-8'
    response['Content-Length'] = len(response.content)
    return response


def check_is_dict(obj):
    if not isinstance(obj, dict):
        raise faults.BadRequest("Request should be a JSON dict")


def is_integer(x):
    return isinstance(x, (int, long))


def are_integer(lst):
    return all(map(is_integer, lst))


def validate_user(user):
    # Check if the user is active.
    if not user.is_active:
        raise faults.Unauthorized('User inactive')

    # Check if the token has expired.
    if user.token_expired():
        raise faults.Unauthorized('Authentication expired')

    # Check if the user has accepted the terms.
    if not user.signed_terms:
        raise faults.Unauthorized('Pending approval terms')


def user_from_token(func):
    @wraps(func)
    def wrapper(request, *args, **kwargs):
        try:
            token = request.x_auth_token
        except AttributeError:
            raise faults.Unauthorized("No authentication token")

        if not token:
            raise faults.Unauthorized("Invalid X-Auth-Token")

        try:
            user = AstakosUser.objects.get(auth_token=token)
        except AstakosUser.DoesNotExist:
            raise faults.Unauthorized('Invalid X-Auth-Token')

        validate_user(user)

        request.user = user
        return func(request, *args, **kwargs)
    return wrapper


def component_from_token(func):
    """Decorator for authenticating component by its token.

    Check that a component with the corresponding token exists. Also,
    if component's token has an expiration token, check that it has not
    expired.

    """
    @wraps(func)
    def wrapper(request, *args, **kwargs):
        try:
            token = request.x_auth_token
        except AttributeError:
            raise faults.Unauthorized("No authentication token")

        if not token:
            raise faults.Unauthorized("Invalid X-Auth-Token")
        try:
            component = Component.objects.get(auth_token=token)
        except Component.DoesNotExist:
            raise faults.Unauthorized("Invalid X-Auth-Token")

        # Check if the token has expired
        expiration_date = component.auth_token_expires
        if expiration_date:
            expires_at = mktime(expiration_date.timetuple())
            if time() > expires_at:
                raise faults.Unauthorized("Authentication expired")

        request.component_instance = component
        return func(request, *args, **kwargs)
    return wrapper


def get_uuid_displayname_catalogs(request, user_call=True):
    # Normal Response Codes: 200
    # Error Response Codes: BadRequest (400)

    try:
        input_data = json.loads(request.body)
    except:
        raise faults.BadRequest('Request body should be json formatted.')
    else:
        if not isinstance(input_data, dict):
            raise faults.BadRequest(
                'Request body should be a json formatted dictionary')
        uuids = input_data.get('uuids', [])
        if uuids is None and user_call:
            uuids = []
        displaynames = input_data.get('displaynames', [])
        if displaynames is None and user_call:
            displaynames = []
        user_obj = AstakosUser.objects
        d = {'uuid_catalog': user_obj.uuid_catalog(uuids),
             'displayname_catalog': user_obj.displayname_catalog(displaynames)}

        response = HttpResponse()
        response.content = json.dumps(d)
        response['Content-Type'] = 'application/json; charset=UTF-8'
        response['Content-Length'] = len(response.content)
        return response


def send_feedback(request, email_template_name='im/feedback_mail.txt'):
    form = FeedbackForm(request.POST)
    if not form.is_valid():
        logger.error("Invalid feedback request: %r", form.errors)
        raise faults.BadRequest('Invalid data')

    msg = form.cleaned_data['feedback_msg']
    data = form.cleaned_data['feedback_data']
    try:
        send_feedback_func(msg, data, request.user, email_template_name)
    except:
        return HttpResponse(status=502)
    return HttpResponse(status=200)


def rename_meta_key(d, old, new):
    if old not in d:
        return
    d[new] = d[old]
    del(d[old])


def get_int_parameter(p):
    if p is not None:
        try:
            p = int(p)
        except ValueError:
            return None
        if p < 0:
            return None
    return p


def get_content_length(request):
    content_length = get_int_parameter(request.META.get('CONTENT_LENGTH'))
    if content_length is None:
        raise faults.LengthRequired('Missing or invalid Content-Length header')
    return content_length


def invert_dict(d):
    return dict((v, k) for k, v in d.iteritems())
