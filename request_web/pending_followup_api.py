from fastapi import Depends,HTTPException
from material_store import pending_followup,repository as repo


def register(api,require_admin):
    @api.post('/api/admin/allocation/{request_id}/follow-up')
    def save_followup(request_id:str,body:dict,actor:str=Depends(require_admin)):
        try:return pending_followup.save(actor,request_id,body)
        except repo.VersionConflict as exc:raise HTTPException(409,str(exc)) from exc
        except (ValueError,TypeError) as exc:raise HTTPException(422,str(exc)) from exc
