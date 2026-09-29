import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__))))

from app.memory.api import record_experience, build_context, reflect, update_project_knowledge

user_id = 'e2e_user'

print('\n--- E2E INTERACTION 1: Explicit Preference ---')
obj_1 = 'Create a compact technical report. I prefer compact reports.'
state_1 = {
    'status': 'success',
    'artifacts': [{'path': 'report.pdf'}]
}
exp_id = record_experience(user_id, obj_1, state_1)
print(f'Recorded experience: {exp_id}')
reflect(user_id, obj_1)
print('Triggered reflection.')

print('\n--- E2E INTERACTION 2: Unrelated Task ---')
obj_2 = 'Summarize meeting notes'
state_2 = {'status': 'success'}
record_experience(user_id, obj_2, state_2)
reflect(user_id, obj_2)

print('\n--- E2E INTERACTION 3: Recall Preference ---')
obj_3 = 'Create another technical report'
ctx = build_context(user_id, obj_3)
print('BUILT CONTEXT:')
print('  User Preferences:', repr(ctx.get('user_preferences')))
print('  Relevant Experiences:', len(ctx.get('relevant_experiences')))

print('\n--- E2E PROJECT SCOPING ---')
update_project_knowledge(user_id, 'proj_A', 'overview', 'Project A uses FastAPI')
ctx_A = build_context(user_id, 'Status', project_id='proj_A')
ctx_B = build_context(user_id, 'Status', project_id='proj_B')
print('Proj A Knowledge:', ctx_A.get('project_knowledge'))
print('Proj B Knowledge:', ctx_B.get('project_knowledge'))

print('\n--- E2E FAILURE LEARNING ---')
record_experience(user_id, 'Deploy strategy A', {'status': 'failed', 'error': 'Timeout'})
record_experience(user_id, 'Deploy strategy B', {'status': 'success'})
ctx_fail = build_context(user_id, 'Deploy again')
print('Relevant Experiences on Deploy:')
for e in ctx_fail.get('relevant_experiences', []):
    print(' -', repr(e))

print('\n--- E2E HINDSIGHT FAILURE ---')
# Temporarily sabotage hindsight URL to something invalid or delete DB
try:
    from app.memory.api import _okf_manager
    _okf_manager.storage_dir = '/invalid_path_that_fails_read_write'
    ctx_err = build_context(user_id, 'Failure test')
    print('Context on Failure (Preferences):', repr(ctx_err.get('user_preferences')))
    print('Context on Failure (Experiences):', ctx_err.get('relevant_experiences'))
except Exception as e:
    print(f'ERROR: Graceful degradation failed. Crash: {e}')

