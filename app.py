import json
from pyscript import document, window
from pyscript.ffi import create_proxy
from diagram import Diagram

editor = document.getElementById('json-input')
status = document.getElementById('status')
current = None

# Embedded default avoids an additional async network dependency.
editor.value = r'''{
  "direction": "TB",
  "nodes": [
    {
      "id": "request",
      "content": "<strong>Project request received</strong><img src=\"https://thumb.wikimedia.org/wikipedia/commons/thumb/8/8a/Overhead_desktop_workspace_%28Unsplash%29.jpg/330px-Overhead_desktop_workspace_%28Unsplash%29.jpg\" alt=\"Keyboard and stationery on a desk\" width=\"160\" height=\"90\"><p>Confirm requirements and goals</p>",
      "to": {
        "review": "Start review"
      }
    },
    {
      "id": "review",
      "content": "<strong>Review and assessment</strong><p>Check requirements, technology, and policy</p>",
      "children": [
        {
          "id": "collect",
          "content": "<strong>Gather information</strong><p>Collect documents and initial specifications</p>",
          "to": {
            "tech": "Technical check",
            "legal": "Policy check"
          }
        },
        {
          "id": "tech",
          "content": "<strong>Technical assessment</strong><p>Confirm feasibility and cost</p>",
          "to": {
            "decision": "Review complete"
          }
        },
        {
          "id": "legal",
          "content": "<strong>Policy assessment</strong><p>Check compliance and risk</p>",
          "to": {
            "decision": "Review complete"
          }
        },
        {
          "id": "decision",
          "content": "<strong>Decision</strong><p>Approve or request changes</p>",
          "children": [
            {
              "id": "approved",
              "content": "<strong>Approve</strong><p>Proceed to execution</p>",
              "to": {
                "plan": "Approved"
              }
            },
            {
              "id": "revise",
              "content": "<strong>Request changes</strong><p>Add information and review again</p>",
              "to": {
                "collect": "Revise and retry"
              }
            }
          ]
        }
      ]
    },
    {
      "id": "execution",
      "content": "<strong>Execution plan</strong><p>From planning to delivery</p>",
      "children": [
        {
          "id": "plan",
          "content": "<strong>Plan</strong><p>Define scope and schedule</p>",
          "to": {
            "build": "Start work"
          }
        },
        {
          "id": "build",
          "content": "<strong>Build</strong><p>Complete the work</p>",
          "to": {
            "qa": "Submit for testing"
          }
        },
        {
          "id": "qa",
          "content": "<strong>Test</strong><p>Check the result against requirements</p>",
          "to": {
            "build": "Changes needed",
            "release": "Tests passed"
          }
        },
        {
          "id": "release",
          "content": "<strong>Deliver</strong><p>Prepare deliverables</p>",
          "to": {
            "finish": "Delivered"
          }
        }
      ]
    },
    {
      "id": "finish",
      "content": "<strong>Done</strong><p>Record results and notify stakeholders</p>"
    }
  ]
}'''

def update_zoom_label(scale):
    document.getElementById('zoom-reset').textContent = '%d%%' % round(scale * 100)

def zoom_in(event=None):
    if current is not None:
        current.set_zoom(current.zoom * 1.25)

def zoom_out(event=None):
    if current is not None:
        current.set_zoom(current.zoom / 1.25)

def zoom_reset(event=None):
    if current is not None:
        current.set_zoom(1.0)

def render_click(event=None):
    global current
    try:
        candidate = Diagram.model_validate_json(editor.value)
        if current is not None:
            current.destroy()
        candidate.on_zoom = update_zoom_label
        current = candidate.mount('diagram')
        update_zoom_label(current.zoom)
        status.textContent = 'Loaded %s nodes.' % len(current.nodes_flat)
        status.className = 'status'
    except Exception as exc:
        status.textContent = 'Could not load: ' + str(exc)
        status.className = 'status error'

def load_file(event):
    files = event.target.files
    if not files or files.length == 0:
        return
    reader = window.FileReader.new()
    def loaded(_event):
        editor.value = reader.result
        render_click()
        document.getElementById('file-input').value = ''
    # Keep the Python callback alive until the browser finishes reading.
    proxy = create_proxy(loaded)
    active_readers.append((reader, proxy))
    reader.addEventListener('load', proxy)
    reader.readAsText(files.item(0), 'UTF-8')

active_readers = []
file_proxy = create_proxy(load_file)
document.getElementById('file-input').addEventListener('change', file_proxy)
click_proxy = create_proxy(render_click)
document.getElementById('render-button').addEventListener('click', click_proxy)
zoom_in_proxy = create_proxy(zoom_in)
zoom_out_proxy = create_proxy(zoom_out)
zoom_reset_proxy = create_proxy(zoom_reset)
document.getElementById('zoom-in').addEventListener('click', zoom_in_proxy)
document.getElementById('zoom-out').addEventListener('click', zoom_out_proxy)
document.getElementById('zoom-reset').addEventListener('click', zoom_reset_proxy)
render_click()
