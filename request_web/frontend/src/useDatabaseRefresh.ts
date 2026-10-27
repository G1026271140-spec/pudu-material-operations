import { useEffect, useRef } from "react";

/** Refresh business values on database revisions without resetting form state. */
export function useDatabaseRefresh(refresh:()=>Promise<unknown>){
  const callback=useRef(refresh);callback.current=refresh;
  useEffect(()=>{
    if(document.querySelector('meta[name="pudu-data-source"]')?.getAttribute('content')!=="postgresql")return;
    let revision="",busy=false,stopped=false;
    const controller=new AbortController();
    async function check(force=false){
      if(busy||stopped||document.visibilityState==="hidden")return;
      busy=true;
      try{
        const response=await fetch('/api/catalog/revision',{cache:'no-store',signal:controller.signal});
        if(!response.ok)return;
        const next=await response.json();
        if((revision&&next.revision!==revision)||force)await callback.current();
        revision=next.revision||"";
      }catch{/* Keep current values and retry on the next visible revision check. */}
      finally{busy=false;}
    }
    const checkChanged=()=>{void check(true);};
    const checkVisible=()=>{void check();};
    void check();
    const timer=window.setInterval(checkVisible,3000);
    const channel=typeof BroadcastChannel!=="undefined"?new BroadcastChannel('pudu-business-data'):null;
    if(channel)channel.onmessage=checkChanged;
    window.addEventListener('pudu-business-data-changed',checkChanged);
    window.addEventListener('focus',checkChanged);
    document.addEventListener('visibilitychange',checkVisible);
    return()=>{stopped=true;controller.abort();channel?.close();window.clearInterval(timer);window.removeEventListener('pudu-business-data-changed',checkChanged);window.removeEventListener('focus',checkChanged);document.removeEventListener('visibilitychange',checkVisible);};
  },[]);
}
