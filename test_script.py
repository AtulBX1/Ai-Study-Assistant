import os
files = [f for f in os.listdir('backend/models') if os.path.isfile(os.path.join('backend/models', f))]
print('\n'.join(files))