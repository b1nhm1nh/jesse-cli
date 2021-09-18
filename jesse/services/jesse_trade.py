import requests
from starlette.responses import JSONResponse
from jesse.services.auth import get_access_token


def feedback(description: str, ticket: bool) -> JSONResponse:
    access_token = get_access_token()

    res = requests.post(
        'https://jesse.trade/api/feedback', {
            'description': description,
            'ticket': ticket
        },
        headers={'Authorization': f'Bearer {access_token}'}
    )

    success_message = 'Feedback submitted successfully'
    error_message = f"{res.status_code} error: {res.json()['message']}"

    return JSONResponse({
        'status': 'success' if res.status_code == 200 else 'error',
        'message': success_message if res.status_code == 200 else error_message
    }, status_code=200)


def report_exception(description: str, traceback: str, ticket: bool) -> JSONResponse:
    access_token = get_access_token()

    res = requests.post(
        'https://jesse.trade/api/exception', {
            'description': description,
            'traceback': traceback,
            'ticket': ticket
        },
        headers={'Authorization': f'Bearer {access_token}'}
    )

    success_message = 'Exception report submitted successfully'
    error_message = f"{res.status_code} error: {res.json()['message']}"

    return JSONResponse({
        'status': 'success' if res.status_code == 200 else 'error',
        'message': success_message if res.status_code == 200 else error_message
    }, status_code=200)


def get_tickets():
    access_token = get_access_token()

    res = requests.get(
        'https://jesse.trade/api/tickets',
        headers={'Authorization': f'Bearer {access_token}'}
    )

    if res.status_code != 200:
        return JSONResponse({
            'status': 'error',
            'message': res.json()['message']
            }, res.status_code)


    return JSONResponse({
        'status': 'success',
        'data': res.json()
    })


def create_ticket(description: str, title: str) -> JSONResponse:
    access_token = get_access_token()

    res = requests.post(
        'https://jesse.trade/api/ticket', {
            'description': description,
            'title': title,
            'type': 'user_created'
        },
        headers={'Authorization': f'Bearer {access_token}'}
    )

    if res.status_code != 200:
        return JSONResponse({
            'status': 'error',
            'message': res.json()['message']
            }, res.status_code)

    return JSONResponse({
        'status': 'success',
        'message': 'Ticket created successfully.',
        'ticket_id': res.json()['ticket_id']
    }, status_code=200)


def seen_message(ticket_id: int) -> JSONResponse:
    access_token = get_access_token()

    res = requests.post(
        'https://jesse.trade/api/message/seen', {
            'ticket_id': ticket_id,
        },
        headers={'Authorization': f'Bearer {access_token}'}
    )

    if res.status_code != 200:
        return JSONResponse({
            'status': 'error',
            'message': res.json()['message']
            }, res.status_code)

    if res.status_code == 200:
        return JSONResponse({
            'status': 'success',
            'message': res.json()['message']
            }, res.status_code)


def add_message(ticket_id: int, description: str) -> JSONResponse:
    access_token = get_access_token()

    res = requests.post(
        'https://jesse.trade/api/message', {
            'ticket_id': ticket_id,
            'description': description
        },
        headers={'Authorization': f'Bearer {access_token}'}
    )

    if res.status_code != 200:
        return JSONResponse({
            'status': 'error',
            'message': res.json()['message']
            }, res.status_code)

    if res.status_code == 200:
        return JSONResponse({
            'status': 'success',
            'message': 'Message created successfully'
            }, res.status_code)


def edit_message(ticket_id: int,message_id: int ,description: str) -> JSONResponse:
    access_token = get_access_token()

    res = requests.post(
        'https://jesse.trade/api/message', {
            'ticket_id': ticket_id,
            'message_id': message_id,
            'description': description
        },
        headers={'Authorization': f'Bearer {access_token}'}
    )

    if res.status_code != 200:
        return JSONResponse({
            'status': 'error',
            'message': res.json()['message']
            }, res.status_code)

    if res.status_code == 200:
        return JSONResponse({
            'status': 'success',
            'message': 'Message created successfully'
            }, res.status_code)