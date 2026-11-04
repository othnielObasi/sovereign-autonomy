/* Separate visual iteration. No operational APIs, live commands or learning writes. */
(() => {
  const learning=document.getElementById('learning-transfer');
  const flow=document.createElement('div');flow.className='learning-flow';flow.setAttribute('aria-label','Illustrative governed knowledge lifecycle');
  const labels=[['A','Robot A discovers','An obstacle or external information starts a candidate.'],['01','Validate','Check evidence, safety and operating scope.'],['02','Approve this version','An operator reviews before an explicit release.'],['B · C','Compatible recipients','Each recipient checks the approved version and context.'],['D','Different platform','Future development: control skills do not transfer here.']];
  labels.forEach(([icon,title,copy])=>{const card=document.createElement('div');const symbol=document.createElement('span');symbol.className='flow-robot';symbol.textContent=icon;const heading=document.createElement('strong');heading.textContent=title;const description=document.createElement('small');description.textContent=copy;card.append(symbol,heading,description);flow.append(card);});
  learning.querySelector('.transfer-label').after(flow);
  const boundary=document.createElement('p');boundary.className='preview-boundary';boundary.textContent='Today: signed, context-filtered route experience and independent execution checks. This interactive review-and-release flow is proposed. Robot D represents future cross-platform development; this demo does not transfer control skills or model weights.';flow.after(boundary);
  const evidence=learning.querySelector('.transfer-evidence');const details=document.createElement('details');details.className='transfer-evidence-details';const summary=document.createElement('summary');summary.textContent='Inspect the example evidence and checks';details.append(summary);evidence.before(details);details.append(evidence);
  const descriptions=[
    'Robot A finds a blocked aisle. A facility notice adds context. The candidate lesson stays unshared.',
    'Check the evidence and the proposed route advice. This version must pass before review.',
    'An operator reviews this version and its scope. Approval allows sharing; it never permits movement.',
    'Offer the approved version to Robots B and C. A mismatched map or robot profile blocks receipt.',
    'Shared advice can improve a route proposal. Each robot still needs its own current safety checks and movement permit.'
  ];
  const previous=v2RenderTransfer;
  v2RenderTransfer=function(){previous();document.getElementById('transfer-description').textContent=descriptions[v2Transfer.step];const active=v2Transfer.step===0?0:v2Transfer.step===1?1:v2Transfer.step===2?2:3;[...flow.children].forEach((card,i)=>card.dataset.active=String(i===active));};
  // Earlier listeners captured the previous renderer; finish every relevant interaction with this layer.
  learning.addEventListener('click',()=>v2RenderTransfer());learning.addEventListener('change',()=>v2RenderTransfer());
  v2RenderTransfer();
  const families=document.querySelector('.platform-families');const capabilityDetail=document.createElement('details');capabilityDetail.className='capability-detail';const capSummary=document.createElement('summary');capSummary.textContent='Explore the five capability areas';families.before(capabilityDetail);capabilityDetail.append(capSummary,families);
  document.querySelector('#capability-overview .intro p').textContent='Set the mission. Check every move. Reuse trusted experience. Open the capability areas when you want the detail.';

  function initFilm(){
    const host=document.getElementById('mission-story'),steps=JSON.parse(document.getElementById('mission-story-data').textContent).steps;
    host.querySelector('.story-context p').textContent='Watch the actual facility renderer replay a saved delivery. A person approaches, a move is refused, and continuation needs fresh permission.';
    host.querySelector('.story-recording-label').textContent='Actual 3D facility renderer · archived simulator data · edited highlights';
    const map=host.querySelector('.story-visual'),layout=host.querySelector('.story-layout'),source=document.createElement('details');source.className='film-source';
    const summary=document.createElement('summary');summary.textContent='Inspect the recorded floor plan and source positions';source.append(summary,map);layout.after(source);
    const film=document.createElement('div');film.className='mission-film';film.innerHTML='<div class="film-title"><strong>Robot-2 · Formulation → Quality lab</strong><span>Saved run · 3 November 2026</span></div><video id="mission-film" playsinline preload="metadata" muted poster="/home/mission-film/plan.webp" aria-label="Recorded simulator data replayed in the actual 3D facility"><track kind="captions" src="/home/mission-film/captions.vtt" srclang="en" label="English decisions" default></video><p id="film-caption" class="film-captions"></p><div class="film-transport"><button id="film-play" type="button" aria-controls="mission-film">Play mission replay</button><button id="film-restart" type="button" aria-controls="mission-film">Restart</button><output id="film-status" role="status">Ready · Plan</output></div><div class="film-media-controls"><label for="film-speed">Playback speed</label><select id="film-speed"><option value="1">Normal</option><option value="0.75">Slower</option><option value="1.5">Faster</option></select></div><p id="film-buffering" class="film-buffering" role="status" hidden>Loading this recorded segment…</p><p class="film-note">New rendering of saved telemetry through our actual 3D facility. Edited timing and visual smoothing; not original video, a live feed or a physical-robot test. <a href="/home/mission-film/provenance.json">Inspect replay provenance ↗</a></p>';
    layout.prepend(film);
    const video=document.getElementById('mission-film'),play=document.getElementById('film-play'),status=document.getElementById('film-status'),caption=document.getElementById('film-caption'),buffer=document.getElementById('film-buffering');
    const names=['plan','move','stop','replan','arrive'],captions=[
      'The destination is set. A route proposes how to get there.',
      'A movement permit is used. Saved observations show the robot leaving its start.',
      'A person is 0.378 m away. The next move is refused; a STOP is acknowledged.',
      'The destination stays the same. A replacement plan needs fresh permission.',
      'The robot reaches the Quality lab. The final STOP is acknowledged.'
    ];
    let index=-1,playing=false,internal=false,loadSequence=0;
    function text(){play.textContent=playing?'Pause mission replay':'Play mission replay';status.textContent=(playing?'Playing':'Paused')+' · '+steps[index].label+' · '+(index+1)+' / 5';}
    async function startVideo(){const sequence=loadSequence;try{await video.play();if(sequence===loadSequence&&!playing)video.pause();}catch{if(sequence===loadSequence){playing=false;text();status.textContent='Playback paused. Press Play to retry.';}}}
    function choose(next){if(next===index)return;loadSequence++;index=next;video.pause();video.src='/home/mission-film/'+names[index]+'.webm';video.poster='/home/mission-film/'+names[index]+'.webp';caption.textContent=captions[index];
      // Each independent chapter supplies its own accurate accessible caption.
      // Disable and replace the old track: mutating src can retain cues across chapter changes.
      [...video.textTracks].forEach(track=>{track.mode='disabled';});video.querySelectorAll('track').forEach(track=>track.remove());
      const track=document.createElement('track');track.kind='captions';track.srclang='en';track.label='English decisions';track.src='/home/mission-film/'+names[index]+'.vtt';video.append(track);track.track.mode='showing';
      video.load();text();if(playing)void startVideo();}
    function sync(){const next=names.indexOf(host.dataset.phase);if(next>=0)choose(next);if(next>=0)document.getElementById('story-description').textContent=captions[next];}
    const observer=new MutationObserver(sync);observer.observe(host,{attributes:true,attributeFilter:['data-phase']});
    play.addEventListener('click',()=>{playing=!playing;if(playing){if(video.ended){video.currentTime=0;}void startVideo();}else video.pause();text();});
    document.getElementById('film-restart').addEventListener('click',()=>{playing=false;video.pause();host.querySelector('[data-story-step="0"]').click();if(index===0){video.currentTime=0;text();}status.textContent='Ready · Plan';});
    host.querySelectorAll('[data-story-step],#story-next,#story-previous').forEach(button=>button.addEventListener('click',()=>{if(!internal){playing=false;video.pause();text();}},true));
    video.addEventListener('ended',()=>{if(!playing)return;if(index===4){playing=false;text();status.textContent='Replay complete · Arrival and STOP recorded';return;}internal=true;host.querySelectorAll('[data-story-step]')[index+1].click();internal=false;sync();});
    video.addEventListener('waiting',()=>{buffer.hidden=false;});video.addEventListener('playing',()=>{buffer.hidden=true;});video.addEventListener('loadeddata',()=>{buffer.hidden=true;});
    video.addEventListener('error',()=>{playing=false;buffer.hidden=true;text();status.textContent='Segment unavailable. Read the recorded decision or inspect its source below.';});
    document.getElementById('film-speed').addEventListener('change',event=>{video.playbackRate=Number(event.target.value);});
    video.addEventListener('loadedmetadata',()=>{video.playbackRate=Number(document.getElementById('film-speed').value);});
    document.addEventListener('visibilitychange',()=>{if(document.hidden){playing=false;video.pause();text();}});window.addEventListener('pagehide',()=>video.pause());
    choose(0);sync();
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',initFilm,{once:true});else initFilm();
})();

