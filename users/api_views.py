from rest_framework.authtoken.models import Token
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from django.contrib.auth import authenticate
from .serializers import UserSerializer
from .models import User


@api_view(['POST'])
@permission_classes([AllowAny])
def api_login(request):
    username = request.data.get('username', '').strip()
    password = request.data.get('password', '')
    print(username, password)
    user = authenticate(request, username=username, password=password)
    if user is None:
        return Response({'error': 'Usuario o contraseña incorrectos'}, status=401)
    if not user.status:
        return Response({'error': 'Usuario inactivo'}, status=403)
    token, _ = Token.objects.get_or_create(user=user)
    return Response({
        'token': token.key,
        'user': UserSerializer(user).data,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_logout(request):
    try:
        request.user.auth_token.delete()
    except Exception:
        pass
    return Response({'ok': True})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_me(request):
    return Response(UserSerializer(request.user).data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_users_list(request):
    users = User.objects.filter(status=True).order_by('username')
    return Response(UserSerializer(users, many=True).data)
