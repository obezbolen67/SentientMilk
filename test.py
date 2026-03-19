def greet(name):
    """A simple function to greet someone."""
    return f"Hello, {name}!"

if __name__ == "__main__":
    user = "World"
    message = greet(user)
    print(message)

    # Simple calculation example
    numbers = [1, 2, 3, 4, 5]
    total = sum(numbers)
    print(f"The sum of {numbers} is {total}.")
