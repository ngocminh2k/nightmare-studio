import sqlite3
import json

db = sqlite3.connect('data/studio.db')
c = db.cursor()
row = c.execute('SELECT storyboard_json FROM episodes WHERE id = ?', ('812b393b-d263-4670-a144-60c7e89b65b0',)).fetchone()
scenes = json.loads(row[0])

changed = 0
for s in scenes:
    num = int(s['number'])
    if num == 91:
        # replace whatever is between "Action and context: " and ". Lighting:"
        p = s['prompt']
        start = p.find('Action and context:')
        end = p.find('Lighting:')
        if start != -1 and end != -1:
            s['prompt'] = p[:start] + 'Action and context: Pale and nervous young informant sitting across from the composed investigator in the dimly lit parlor. ' + p[end:]
            changed += 1
            print('Updated scene 091')
    elif num == 96:
        p = s['prompt']
        start = p.find('Action and context:')
        end = p.find('Lighting:')
        if start != -1 and end != -1:
            s['prompt'] = p[:start] + 'Action and context: The investigator firmly snapping shut his leather-bound notebook with deliberate composure while the young witness looks on. ' + p[end:]
            changed += 1
            print('Updated scene 096')

if changed:
    c.execute('UPDATE episodes SET storyboard_json = ? WHERE id = ?', (json.dumps(scenes), '812b393b-d263-4670-a144-60c7e89b65b0'))
    db.commit()
    print(f'Saved {changed} sanitized prompts to database.')
