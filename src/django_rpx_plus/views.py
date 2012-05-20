from django.conf import settings
import django.contrib.auth as auth
from django.contrib.auth.models import User
from django.shortcuts import render_to_response, redirect
from django.template import RequestContext
from django.core.urlresolvers import reverse
from django.contrib.auth.decorators import login_required
from django.utils.translation import ugettext_lazy as _

#The reason why we use django's urlencode instead of urllib's urlencode is that
#django's version can operate on unicode strings.
from django.utils.http import urlencode

#The messages framework will only be available from django 1.2 onwards. Since
#most people are still using <= 1.1.1, we fallback on the backported message
#framework:
try:
    from django.contrib import messages
except ImportError:
    import django_messages_framework as messages #backport of messages framework

#In django 1.2 onwards, the CSRF middleware is activated by default. This means
#that when RPX directs the user to POST the token to rpx_response, the request
#will fail since it does not contain the CSRF token. Therefore, we exempt the
#view from CSRF processing.
try:
    from django.views.decorators.csrf import csrf_exempt
except ImportError:
    from django.contrib.csrf.middleware import csrf_exempt


from django_rpx_plus.models import RpxData
from django_rpx_plus.forms import RegisterForm
import django_rpx_plus.signals as signals

import re #for sub in register

#The primary ID to the RpxData object is set in session when user is logged in
#but not registered. The register view checks and uses this session var.
RPX_ID_SESSION_KEY = '_rpxdata_id'

@csrf_exempt
def rpx_response(request):
    '''
    Handles the POST response from RPX API. This is where the user is sent
    after signing in through RPX.

    @param request: Django request object.
    @return: Redirect that takes user to 'next' or LOGIN_REDIRECT_URL.
    '''
    #According to http://rpxwiki.com/Passing-state-through-RPX, the query
    #string parameters in our token url will be POST to our rpx_response so
    #that we can retain some state information. We use this for 'next', a
    #var that specifies where the user should be redirected after successful
    #login.
    destination = request.POST.get('next', settings.LOGIN_REDIRECT_URL)

    if request.method == 'POST':
        #RPX also sends token back via POST. We pass this token to our RPX auth
        #backend which, then, uses the token to access the RPX API to confirm
        #that the user logged in successfully and to obtain the user's login
        #information.
        token = request.POST.get('token', False)
        if token:
            response = auth.authenticate(token = token)
            #The django_rpx_plus auth backend can return three things: None (means
            #that auth has failed), a RpxData object (means that user has passed
            #auth but is not registered), or a User object (means that user is
            #auth AND registered).
            if type(response) == User:
                #Successful auth and user is registered so we login user.
                auth.login(request, response)
                return redirect(destination)
            elif type(response) == RpxData:
                #Successful auth, but user is NOT registered! So we redirect
                #user to the register page. However, in order to tell the
                #register view that the user is authed but not registered,
                #we set a session var that points to the RpxData object
                #primary ID. After the user has been registered, this session
                #var will be removed.
                request.session[RPX_ID_SESSION_KEY] = response.id
                #For security purposes, there could be a case where user
                #decides not to register but then never logs out either.
                #Another person can come along and then use the REGISTER_URL
                #to continue creating the account. So we expire this session
                #after a set time interval. (Note that this session expiry
                #setting will be cleared when user completes registration.)
                request.session.set_expiry(60 * 10) #10 min

                query_params = urlencode({'next': destination})
                return redirect(settings.REGISTER_URL+'?'+query_params)
            else:
                #Do nothing, auth has failed.
                pass

    #Authentication has failed. We'll send user  back to login page where error
    #message is displayed.
    messages.error(request, _('There was an error in signing you in. Try again?'))
    query_params = urlencode({'next': destination})
    return redirect(reverse('auth_login')+'?'+query_params)

@login_required #User needs to be logged into an account in order to associate.
@csrf_exempt
def associate_rpx_response(request):
    '''
    Similar to rpx_response except that the logic for handling the response
    cases is tailored for associating a new RPX login with an existing User.

    @param request: Django request object.
    @return: Redirect user back to 'auth_associate'.
    '''
    #Since this function and rpx_response(...) are very similar, removed much
    #of comments from this function for clarity. Refer to rpx_response's
    #comments if you want to know what's going on.
    if request.method == 'POST':
        #A difference here is that we default redirect to auth_associate
        #instead of LOGIN_REDIRECT_URL.
        destination = request.POST.get('next', reverse('auth_associate'))

        token = request.POST.get('token', False)
        if token:
            response = auth.authenticate(token = token)
            if type(response) == User:
                #Successful auth and user is registered. This means that the
                #login has already been registered. So we display error.
                messages.error(request, _('Sorry, this login has already been associated with another account.'))
            elif type(response) == RpxData:
                #Successful auth, but user is NOT registered! So we associate
                #this RPX login with the current user.
                rpxdata = response #for clarity
                rpxdata.user = request.user
                rpxdata.save()

                messages.success(request, _('We successfully associated your new login!'))
            else:
                #Do nothing, auth has failed.
                messages.error(request, _('There was an error in signing you in. Try again?'))

    return redirect(destination)

def login(request):
    '''
    Displays the RPX login page.

    @param request: Django request object.
    @return: Rendered login.html page.
    '''
    next = request.GET.get('next', settings.LOGIN_REDIRECT_URL)
    extra = {'next': next}

    return render_to_response('django_rpx_plus/login.html', {
                                'extra': extra,
                              },
                              context_instance = RequestContext(request))

def register(request):
    '''
    Checks to see if user is logged in and unregistered. Then displays and
    handles form for creating a new User. Then associates the user's RPX login
    with the newly created User.

    @param request: Django request object.
    @return: Rendered register.html or redirect user.
    '''
    #See if a redirect param is specified. If not, we will default to
    #LOGIN_REDIRECT_URL.
    next = request.GET.get('next', settings.LOGIN_REDIRECT_URL)

    #In order to use register, user MUST have the session var RPX_ID_SESSION_KEY
    #set to the user's RpxData object. This indicates that the user has
    #successfully logged in via RPX but has not previously registered.
    try:
        rpxdata_id = request.session[RPX_ID_SESSION_KEY]
        #Check to see if this id exists
        rd = RpxData.objects.get(id = rpxdata_id)
    except (KeyError, RpxData.DoesNotExist):
        return redirect(next)

    #Check form submission.
    if request.method == 'POST':
        form = RegisterForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            #print data

            #We create the new user object and associate it with our RpxData
            #object. Since we don't provide a password, set_unusable_password()
            #will automatically be called:
            u = User.objects.create_user(data['username'], data['email'])

            rd.user = u
            rd.save()

            #Might want to perform some kind of post-registration action so we
            #send a signal. sender is None since we aren't sending within an obj.
            signals.registration_successful.send(sender = None, user = u)

            #Now we log the user in. This also clears out the previous session
            #containing the expiring RPX_ID_SESSION_KEY var. Normally, we get
            #the user directly from auth.authenticate(...) which adds a
            #User.backend attribute. We have to manually add it here:
            u.backend = 'django_rpx_plus.backends.RpxBackend'
            auth.login(request, u)

            return redirect(next)
    else:
        #No form submission so we will display page with initial form data.
        #We try to pre-populate the form with data from the RPX login.
        rpx_profile = rd.profile

        #Clean the username to allow only alphanum and underscore. If no
        #provided names are available, set username to an empty string so that
        #re won't raise TypeError.
        username =  rpx_profile.get('preferredUsername') or \
                    rpx_profile.get('displayName') or ''
        username = re.sub(r'[^\w+]', '', username)

        form = RegisterForm(initial = {
            'username': username,
            'email': rpx_profile.get('email', '')
        })

    return render_to_response('django_rpx_plus/register.html', {
                                'form': form,
                              },
                              context_instance = RequestContext(request))

@login_required
def associate(request):
    '''
    Displays list of associated logins to current User.

    @param request: Django request object.
    @return: Rendered associate.html
    '''
    #Get associated accounts for user.
    user_rpxdatas = RpxData.objects.filter(user = request.user)

    #Our rpx_response is different from our usual URL since we need to use a
    #different view to handle the logic behind associating another account. This
    #is why we pass in 'rpx_response_path'.
    return render_to_response('django_rpx_plus/associate.html', {
                                'rpxdatas': user_rpxdatas,
                                'extra': {'next': reverse('auth_associate')},
                                'rpx_response_path': reverse('associate_rpx_response'),
                              },
                              context_instance = RequestContext(request))

@login_required
def delete_associated_login(request, rpxdata_id):
    '''
    Deletes an associated login from the User.

    @param request: Django request object.
    @type rpxdata_id: integer
    @param rpxdata_id: ID (primary key) of RpxData object to delete.
    @return: Redirect to 'auth_associate'.
    '''
    #Check to see if the rpxdata_id exists and is associated with this user.
    try:
        #We only allow deletion if user has more than one login
        num_logins = RpxData.objects.filter(user = request.user).count()
        if num_logins > 1:
            #Okay, so we can delete this RPX login:
            r = RpxData.objects.get(id = rpxdata_id, user = request.user)
            messages.success(request, _('Your %(provider)s login was successfully deleted.') % dict(provider=r.provider))
            r.delete()
    except RpxData.DoesNotExist:
        #Silent error.
        pass

    return redirect('auth_associate')
