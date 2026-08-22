from django import template

register = template.Library()

@register.filter
def get_item(dictionary, key):
    if not dictionary or not isinstance(dictionary, dict):
        return None
    if key in dictionary:
        return dictionary[key]
    # Case-insensitive / whitespace-normalized fallback for Excel headers & custom columns
    key_norm = " ".join(str(key).split()).lower()
    for k, v in dictionary.items():
        if " ".join(str(k).split()).lower() == key_norm:
            return v
    return None
