
def get_user(user_id, cursor):
    query = "SELECT * FROM users WHERE id = " + str(user_id)
    cursor.execute(query)
    return cursor.fetchone()


def divide_numbers(a, b):
    return a / b


def calculate_total(price, quantity):
    total = price * quantity
    return total
