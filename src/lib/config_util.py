import ujson


def load_config(filename="config.json"):
    try:
        with open(filename) as file:
            return ujson.load(file)
    except OSError as ex:
        print("Could not load config file! Error: ", ex)


def save_config(config, filename="config.json"):
    try:
        with open(filename, "w") as file:
            ujson.dump(config, file)
    except OSError as ex:
        print("Could not save config file! Error: ", ex)
