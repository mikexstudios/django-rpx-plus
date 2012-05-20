from django import template
from django.conf import settings
from django.core.urlresolvers import reverse
#The reason why we use django's urlencode instead of urllib's urlencode is that
#django's version can operate on unicode strings.
from django.utils.http import urlencode

from django_rpx_plus.helpers import django_lang_code_to_rpx_lang_preference

register = template.Library()

def _rpx_common(request, extra = '', rpx_response = False):
    '''
    Common code for rpx_* template inclusion tags. Returns a template vars
    dict for use in rpx tag templates.

    @param request: Django request object.
    @type extra: dict
    @param extra: Extra query string/parameters to include in the token_url.
                  Useful for adding GET params that will be passed back to the
                  rpx_response handler. Example usage would be to include a
                  'next' GET param which signifies where the user will be
                  redirected to after successful login. Example input:
                  {'next': 'http://example.com/next_url'}
    @type rpx_response: string
    @param rpx_response: Relative url path to where we will handle the RPX
                         response in our app. This relative path will be used
                         to generate the token_url that is passed to the RPX
                         service.
    @rtype: dict
    @return: Template var dictionary for use in rpx tag template snippets.
    '''
    if extra != '':
        extra = '?'+urlencode(extra)
    if not rpx_response:
        #This is the default rpx_response that will be used most of the time.
        #The only time when we don't use this, is when we need to associate
        #a login, so we end up using a different url.
        rpx_response = reverse('rpx_response')

    #Construct the token url:
    base_host = getattr(settings, 'RPX_BASE_SITE_HOST', request.get_host())
    #Also check for empty var:
    if not base_host:
        base_host = request.get_host()
    token_url = "http://%s%s%s" % (base_host,
                                   rpx_response,
                                   extra)

    #If LocaleMiddleware is being used, request.LANGUAGE_CODE is set. We will allow
    #the LANGUAGE_CODE to override settings.RPX_LANGUAGE_PREFERENCE. However, since
    #django's LANGUAGE_CODE does not map cleanly to RPX's language preference, we
    #make a best attempt through helpers.django_lang_code_to_rpx_lang_preference.
    #If neither request.LANGUAGE_CODE nor settings.RPX_LANGUAGE_PREFERENCE is set,
    #we will default to settings.LANGUAGE_CODE (which is usually 'en-us').
    try:
        language_preference = django_lang_code_to_rpx_lang_preference(request.LANGUAGE_CODE)
    except AttributeError:
        #If settings.RPX_LANGUAGE_PREFERENCE isn't set, then we will use
        #settings.LANGUAGE_CODE
        language_preference = getattr(settings, 'RPX_LANGUAGE_PREFERENCE',
                                      django_lang_code_to_rpx_lang_preference(settings.LANGUAGE_CODE))
    #print language_preference
    return {
        'realm': settings.RPXNOW_REALM,
        'token_url': token_url,
        'language_preference': language_preference,
    }


@register.inclusion_tag('django_rpx_plus/rpx_link.html', takes_context = True)
def rpx_link(context, text, extra = '', rpx_response = False):
    '''
    Template tag that returns an HTML link that, when clicked, displays
    the RPX login widget in a popup. Requires including rpx_script.html
    in the page before </body> (which you can do by using
    {% rpx_script %}). The way it works is by returning HTML like:
        <a class="rpxnow" onclick="return false;" href="[rpx link]"> [text]</a>
    rpx_script's javascript watches for links with class="rpxnow" to trigger
    the popup. And returning false for onclick keeps the link from continuing.

    However, if you don't want to use the popup widget and instead want the
    link to continue (which will take the user to a simple RPX login page),
    then use the 'rpx_url' tag instead to get just the RPX url. Then in your
    template, write the <a href="..."></a> HTML yourself.

    @param context: Django context object. It's passed automatically because
                    we have takes_context = True for inclusion_tag decorator.
    @type text: string
    @param text: Link text that goes between <a href="..."> and </a>.
    @param extra: See _rpx_common docstring.
    @param rpx_response: See _rpx_common docstring.
    @rtype: dict
    @return: Template var dictionary for use in inclusion template snippet.
    '''
    #NOTE: We have to manually specify each of the args; can't use *args,
    #**kwargs.
    common = _rpx_common(context['request'], extra, rpx_response)

    #Add link text to template var dict
    common['text'] = text

    return common

@register.inclusion_tag('django_rpx_plus/rpx_script.html', takes_context = True)
def rpx_script(context, extra = '', rpx_response = False, flags = ''):
    '''
    Template tag that returns HTML script tags to load the RPX popup widget.
    This is primarily used by the 'rpx_link' tag which outputs an HTML link
    that the user clicks to trigger the popup.

    @param context: Django context object. It's passed automatically because
                    we have takes_context = True for inclusion_tag decorator.
    @param extra: See _rpx_common docstring.
    @param rpx_response: See _rpx_common docstring.
    @type flags: string
    @param flags: Arguments for the RPXNOW.flags = '' var. A good use case
                  would be to set flags = 'show_provider_list' to force showing
                  all login providers even if user is logged in.
    @rtype: dict
    @return: Template var dictionary for use in inclusion template snippet.
    '''
    common = _rpx_common(context['request'], extra, rpx_response)

    #Add additional template vars
    common['flags'] = flags

    return common


@register.inclusion_tag('django_rpx_plus/rpx_embed.html', takes_context = True)
def rpx_embed(context, extra = '', rpx_response = False):
    '''
    Template tag that returns HTML iframe code which displays an embedded
    RPX login widget on the page.

    @param context: Django context object. It's passed automatically because
                    we have takes_context = True for inclusion_tag decorator.
    @param extra: See _rpx_common docstring.
    @param rpx_response: See _rpx_common docstring.
    @rtype: dict
    @return: Template var dictionary for use in inclusion template snippet.
    '''
    common = _rpx_common(context['request'], extra, rpx_response)

    return common


@register.inclusion_tag('django_rpx_plus/rpx_embed.html', takes_context = True)
def rpx_embed_admin(context):
    '''
    Template tag that returns HTML iframe code which displays an embedded
    RPX login widget on a standard admin login page.

    @param context: Django context object. It's passed automatically because
                    we have takes_context = True for inclusion_tag decorator.
    @rtype: dict
    @return: Template var dictionary for use in inclusion template snippet.
    '''
    return rpx_embed(context, extra=dict(next=context['request'].path))


@register.inclusion_tag('django_rpx_plus/rpx_url.html', takes_context = True)
def rpx_url(context, extra = '', rpx_response = False):
    '''
    Template tag that returns a raw link to a login page hosted on RPX
    servers. It is used by the 'rpx_link' tag to include a fallback link
    if the popup widget doesn't trigger. It can also be used to construct
    your own custom <a href="...">...</a> link.

    @param context: Django context object. It's passed automatically because
                    we have takes_context = True for inclusion_tag decorator.
    @param extra: See _rpx_common docstring.
    @param rpx_response: See _rpx_common docstring.
    @rtype: dict
    @return: Template var dictionary for use in inclusion template snippet.
    '''
    common = _rpx_common(context['request'], extra, rpx_response)

    return common
