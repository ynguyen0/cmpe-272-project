from django.utils.cache import patch_cache_control


class PrivateResponseMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if not request.path.startswith("/static/"):
            patch_cache_control(response, no_store=True, private=True)
        return response
