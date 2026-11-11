import sqlite3, json
conn = sqlite3.connect('data/studio.db')
conn.row_factory = sqlite3.Row
ep_id = 'ae61c2f4-2b13-4816-aa9f-9712a1aea264'
jobs = conn.execute(
    'SELECT kind, status, result_json, error FROM jobs WHERE episode_id=? ORDER BY created_at',
    (ep_id,)
).fetchall()
for j in jobs:
    r = json.loads(j['result_json'] or '{}')
    keys = list(r.keys())[:5]
    err = (j['error'] or '')[:50]
    print(f"{j['kind']:<10} {j['status']:<10} result_keys={keys} err={err!r}")

# Xem output_path của episode
ep = conn.execute('SELECT output_path, status FROM episodes WHERE id=?', (ep_id,)).fetchone()
print(f"\noutput_path: {ep['output_path']}")
conn.close()
