# Run Model Tutorial

This walkthrough explains how a `Run` is created with sensible defaults, how those values reach the browser, how the UI sends changes back to Flask, and how everything is saved in SQLite. Follow the flow from Python model to rendered page and back again.

## 1. The Run dataclass provides defaults

Every run starts life as a small dataclass with built-in defaults: no ID yet, 50 total iterations, and an empty name. Because these defaults live in Python, any new run automatically inherits them without extra setup.

```python
# app/models.py
@dataclass
class Run:
    run_enum: Optional[int] = None
    total_iterations: int = 50
    run_name: str = ""
```

## 2. Creating a run writes the defaults to SQLite

When you click **Create New Run**, Flask calls `create_run_route`, which asks the repository layer to insert a row using those default values. The repository ensures the database exists, then executes an `INSERT` with the default iteration count and name. SQLite stores the data in a `runs` table with columns for the ID, iteration count, and name.

```python
# app/app.py
@app.route('/runs/new')
def create_run_route():
    """Creates a new run with default settings and redirects to its detail page."""
    run = repo_create_run()
    if run.run_enum is None:
        raise RuntimeError('Failed to create run')
    return redirect(url_for('run_detail', run_enum=run.run_enum))
```

```python
# app/run_repository.py
def create_run(default_total_iterations: int = 50, default_run_name: str = "") -> Run:
    with _connection() as conn:
        cursor = conn.execute(
            "INSERT INTO runs (total_iterations, run_name) VALUES (?, ?)",
            (default_total_iterations, default_run_name),
        )
        conn.commit()
        run_enum = cursor.lastrowid
    return Run(run_enum=run_enum, total_iterations=default_total_iterations, run_name=default_run_name)
```

```sql
-- app/run_repository.py
CREATE TABLE IF NOT EXISTS runs (
    run_enum INTEGER PRIMARY KEY AUTOINCREMENT,
    total_iterations INTEGER NOT NULL,
    run_name TEXT NOT NULL
);
```

## 3. Flask passes stored values to Jinja templates

After creating or selecting a run, Flask loads the saved row with `get_run` and renders `run.j2`, handing the `Run` instance to the template. Jinja can then read `run.total_iterations` and friends directly.

```python
# app/app.py
@app.route('/runs/<int:run_enum>')
def run_detail(run_enum: int):
    """Displays the configuration and controls for a specific run."""
    run = get_run(run_enum)
    if run is None:
        raise NotFound(f'Run {run_enum} not found.')
    return render_template('run.j2', run=run)
```

```python
# app/run_repository.py
def get_run(run_enum: int) -> Optional[Run]:
    with _connection() as conn:
        row = conn.execute(
            "SELECT run_enum, total_iterations, run_name FROM runs WHERE run_enum = ?",
            (run_enum,),
        ).fetchone()
    if row is None:
        return None
    return Run(run_enum=row['run_enum'], total_iterations=row['total_iterations'], run_name=row['run_name'])
```

## 4. Jinja pre-fills the page

The template shows the run number in the title and summary. Form inputs take their default values from the `Run` object, so the iteration input and name field are populated automatically. The script block also stores the run ID in JavaScript for later requests.

```html
<!-- app/templates/run.j2 -->
<h1>Run {{ run.run_enum }}</h1>
<p class="meta">Name: <strong id="runNameDisplay">{{ run.run_name if run.run_name else 'Not set' }}</strong>
   · Total Iterations: <strong id="runIterationsDisplay">{{ run.total_iterations }}</strong></p>

<input type="number" id="totalIterationsInput" min="1" value="{{ run.total_iterations }}">
<input type="text" id="runNameInput" value="{{ run.run_name }}" placeholder="Enter a name">

<script>
    const runEnum = {{ run.run_enum }};
</script>
```

## 5. The browser sends edits back to Flask

When you press the **Set** button for total iterations, the click handler builds a `fetch` request to `/runs/<run_enum>/total-iterations` with the new number in JSON. Updating the name works the same way: the second handler posts the typed string to `/runs/<run_enum>/run-name`. Both requests include the run ID in the URL so Flask knows which row to update.

```javascript
// app/templates/run.j2
setTotalIterationsBtn.addEventListener('click', () => {
    const value = parseInt(totalIterationsInput.value, 10);
    if (Number.isNaN(value) || value <= 0) {
        addLog('Total iterations must be a positive number.', 'error');
        return;
    }

    fetch(`/runs/${runEnum}/total-iterations`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ total_iterations: value })
    })
        .then(async (response) => {
            const data = await response.json();
            if (!response.ok) {
                throw new Error(data.message || 'Failed to update total iterations.');
            }
            totalIterationsInput.value = data.run.total_iterations;
            runIterationsDisplay.textContent = data.run.total_iterations;
        })
        .catch((error) => {
            addLog(`Failed to update total iterations: ${error.message}`, 'error');
        });
});

setRunNameBtn.addEventListener('click', () => {
    const name = runNameInput.value || '';

    fetch(`/runs/${runEnum}/run-name`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ run_name: name })
    })
        .then(async (response) => {
            const data = await response.json();
            if (!response.ok) {
                throw new Error(data.message || 'Failed to update run name.');
            }
            runNameInput.value = data.run.run_name;
            runNameDisplay.textContent = data.run.run_name || 'Not set';
        })
        .catch((error) => {
            addLog(`Failed to update run name: ${error.message}`, 'error');
        });
});
```

## 6. Flask validates and updates SQLite

The `/runs/<run_enum>/total-iterations` route parses the JSON payload, checks that the value is a positive number, and then calls the repository helper to persist the change. The helper issues an `UPDATE` statement against SQLite, changing only the selected row. The run-name route follows the same pattern: parse and trim the string, write it to the database, and return the updated row.

```python
# app/app.py
@app.route('/runs/<int:run_enum>/total-iterations', methods=['POST'])
def update_total_iterations(run_enum: int):
    payload = request.get_json(silent=True) or {}

    try:
        total_iterations = int(payload.get('total_iterations', 0))
        if total_iterations <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({'message': 'total_iterations must be a positive integer'}), 400

    if not repo_update_total_iterations(run_enum, total_iterations):
        raise NotFound(f'Run {run_enum} not found.')

    run = get_run(run_enum)
    if run is None:
        raise NotFound(f'Run {run_enum} not found.')
    return jsonify({'message': 'total_iterations updated', 'run': _run_to_dict(run)})


@app.route('/runs/<int:run_enum>/run-name', methods=['POST'])
def update_run_name(run_enum: int):
    payload = request.get_json(silent=True) or {}
    run_name = payload.get('run_name')

    if not isinstance(run_name, str):
        return jsonify({'message': 'run_name must be a string'}), 400

    normalized_name = run_name.strip()
    if not repo_update_run_name(run_enum, normalized_name):
        raise NotFound(f'Run {run_enum} not found.')

    run = get_run(run_enum)
    if run is None:
        raise NotFound(f'Run {run_enum} not found.')
    return jsonify({'message': 'run_name updated', 'run': _run_to_dict(run)})
```

```python
# app/run_repository.py
def update_total_iterations(run_enum: int, total_iterations: int) -> bool:
    with _connection() as conn:
        cursor = conn.execute(
            "UPDATE runs SET total_iterations = ? WHERE run_enum = ?",
            (total_iterations, run_enum),
        )
        conn.commit()
    return cursor.rowcount == 1


def update_run_name(run_enum: int, run_name: str) -> bool:
    with _connection() as conn:
        cursor = conn.execute(
            "UPDATE runs SET run_name = ? WHERE run_enum = ?",
            (run_name, run_enum),
        )
        conn.commit()
    return cursor.rowcount == 1
```

## 7. Reloading shows the stored values

Whenever you refresh the run page or visit the dashboard, Flask reads from SQLite so you always see the latest data. The run list uses `list_runs` to pull every row before rendering `index.j2`. Opening an individual run repeats the `get_run` lookup, so the page reflects any changes you made in earlier sessions.

```python
# app/app.py
@app.route('/')
def index():
    """Displays the list of available runs."""
    runs = list_runs()
    return render_template('index.j2', runs=runs)
```

```python
# app/run_repository.py
def list_runs() -> List[Run]:
    with _connection() as conn:
        rows = conn.execute(
            "SELECT run_enum, total_iterations, run_name FROM runs ORDER BY run_enum"
        ).fetchall()
    return [Run(run_enum=row['run_enum'], total_iterations=row['total_iterations'], run_name=row['run_name']) for row in rows]
```

```html
<!-- app/templates/index.j2 -->
{% for run in runs %}
<tr>
    <td>{{ run.run_enum }}</td>
    <td>{{ run.run_name if run.run_name else '—' }}</td>
    <td>{{ run.total_iterations }}</td>
    <td><a class="open-link" href="{{ url_for('run_detail', run_enum=run.run_enum) }}">Open</a></td>
</tr>
{% endfor %}
```

---

**Try it out:** create a run, tweak the iteration count, refresh the page, and notice how the defaults and updates persist thanks to the Run model and the repository layer working together.
