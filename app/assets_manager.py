import os
from PIL import Image
from flask import current_app

MAX_PHOTO_SIZE = 2 * 1024 * 1024
ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp'}
MAX_DIMENSION = 512

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def save_photo(photo, subfolder, filename):
    upload_folder = os.path.join(current_app.static_folder, 'assets', subfolder)
    os.makedirs(upload_folder, exist_ok=True)

    filepath = os.path.join(upload_folder, filename)

    img = Image.open(photo.stream)
    if img.mode in ('RGBA', 'P'):
        img = img.convert('RGB')

    width, height = img.size
    if width > MAX_DIMENSION or height > MAX_DIMENSION:
        if width >= height:
            new_width = MAX_DIMENSION
            new_height = int(height * MAX_DIMENSION / width)
        else:
            new_height = MAX_DIMENSION
            new_width = int(width * MAX_DIMENSION / height)
        img = img.resize((new_width, new_height), Image.LANCZOS)

    img.save(filepath, 'JPEG', quality=85)