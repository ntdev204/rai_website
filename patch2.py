import re

path = r'd:\nckh\rai_website\client\src\app\(dashboard)\analytics\page.tsx'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Replace section headers
content = content.replace('title="6.2.1 · Điều khiển và Chuyển động"', 'title="Điều khiển và Chuyển động"')
content = content.replace('title="6.2.2 · Perception và AI"', 'title="Perception và AI"')
content = content.replace('title="6.2.3 · Dataset"', 'title="Dataset"')
content = content.replace('title="6.2.4 · Safety và Degrade"', 'title="Safety và Degrade"')

# Replace main header
content = content.replace('Analytics — §6.2', 'Analytics Dashboard')
content = content.replace('Chỉ số thực nghiệm · §6.2.1 Điều khiển · §6.2.2 Perception · §6.2.3 Dataset · §6.2.4 Safety', 'Chỉ số thực nghiệm · Điều khiển · Perception · Dataset · Safety')

# Replace ExperimentPanel header
content = content.replace('Kết quả Thực nghiệm §6.3', 'Kết quả Thực nghiệm (Offline & Online)')

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print("PATCH SUCCESS!")
