c = open('C:/Users/win/Documents/study/china-travel-map/frontend/index.html', 'r', encoding='utf-8').read()

# Remove the 2nd and 3rd duplicate if(userPosition) blocks
# Find the pattern: first block ends, then immediately another identical block starts

# Find the addBatch function
idx = c.find('function addBatch()')
end = c.find('function filterData()')

# The click handler has 3 identical if(userPosition) blocks
# We need to remove the 2nd and 3rd
# Pattern: 
#   }\n        if(userPosition){\n          var dist...
# The first block ends with '}'
# Then the 3rd to last line of the click handler is the last '}'

# Find the addBatch click handler boundaries
click_marker = 'm.on("click",function(){'
click_start = c.find(click_marker, idx)
markers_push = 'markers.push(m)'
click_end = c.find(markers_push, click_start)

click_handler = c[click_start:click_end]

# Find positions of if(userPosition) blocks
pos1 = click_handler.find('if(userPosition){')
block1_end = click_handler.find('}', pos1) + 1  # include closing brace

pos2 = click_handler.find('if(userPosition){', block1_end)
block2_end = click_handler.find('}', pos2) + 1

pos3 = click_handler.find('if(userPosition){', block2_end)
block3_end = click_handler.find('}', pos3) + 1

print(f'Block 1: {pos1}-{block1_end}')
print(f'Block 2: {pos2}-{block2_end}')
print(f'Block 3: {pos3}-{block3_end}')

# Remove blocks 2 and 3 from click_handler
new_click = click_handler[:block1_end] + click_handler[block3_end:]

# Also fix the invalid \\U escape in block 1
# Replace \\U0001F4CD with 📍 (the HTML entity used in other blocks)
new_click = new_click.replace('\\U0001F4CD', '📍')
new_click = new_click.replace('\\uD83D\\uDCCD', '📍')

print(f'Click handler before: {len(click_handler)} chars')
print(f'Click handler after: {len(new_click)} chars')

# Reconstruct the file
new_c = c[:click_start] + new_click + c[click_end:]

open('C:/Users/win/Documents/study/china-travel-map/frontend/index.html', 'w', encoding='utf-8').write(new_c)
print('\\nUpdated index.html')