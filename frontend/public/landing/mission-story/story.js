/* Guided highlights only: no operational APIs or robot commands. */
(() => {
  const host = document.getElementById('mission-story');
  if (!host) return;
  const recording = JSON.parse(document.getElementById('mission-story-data').textContent);
  const svgNS = 'http://www.w3.org/2000/svg';
  const buttons = [...host.querySelectorAll('[data-story-step]')];
  let index = 0;
  function centerMap() {
    const box = host.querySelector('.story-map-scroll');
    const bounds = document.getElementById('story-map').getBoundingClientRect();
    const pose = recording.steps[index].pose;
    box.scrollLeft = Math.max(0, pose.x / 36 * bounds.width - box.clientWidth / 2 + 12);
    box.scrollTop = Math.max(0, (26 - pose.y) / 26 * bounds.height - box.clientHeight / 2 + 18);
  }
  function svg(tag, attributes) {
    const node = document.createElementNS(svgNS, tag);
    for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value));
    return node;
  }
  const point = ([x, y]) => `${x * 20},${(26 - y) * 20}`;
  const text = (id, value) => { document.getElementById(id).textContent = value; };
  function show(next) {
    index = Math.max(0, Math.min(recording.steps.length - 1, next));
    const step = recording.steps[index];
    buttons.forEach((button, i) => button.setAttribute('aria-pressed', String(i === index)));
    text('story-title', step.title);
    text('story-description', step.text);
    text('story-status', step.status);
    text('story-count', `0${index + 1} / 05`);
    text('story-fact-label', step.fact_label);
    text('story-fact', step.fact);
    text('story-time', step.time_range);
    text('story-event-ids', step.event_ids.join(' · '));
    text('story-map-caption', index === 2
      ? 'Recorded robot and worker positions at the refused move. Dashed line: proposed route; solid line: recorded positions up to this moment.'
      : 'Facility floor plan with recorded robot positions. Dashed line: proposed route; solid line: recorded positions up to this moment. Intermediate moments are omitted.');
    host.dataset.phase = step.label.toLowerCase();
    const map = document.getElementById('story-map');
    map.setAttribute('aria-label', `Recorded facility floor plan. ${step.title}. ${step.status}.`);
    const route = step.route || recording.steps[0].route;
    document.getElementById('story-proposed-route').setAttribute('points', route.map(point).join(' '));
    document.getElementById('story-recorded-trail').setAttribute('points', step.trail.map(point).join(' '));
    document.getElementById('story-robot').setAttribute('transform', `translate(${point([step.pose.x, step.pose.y]).replace(',', ' ')})`);
    const people = document.getElementById('story-people');
    people.replaceChildren();
    for (const person of step.people || []) {
      people.append(svg('circle', { cx: person.x * 20, cy: (26 - person.y) * 20, r: 7, fill: '#bc6127', stroke: '#fff', 'stroke-width': 2 }));
    }
    const proximity = document.getElementById('story-proximity');
    proximity.setAttribute('cx', step.pose.x * 20);
    proximity.setAttribute('cy', (26 - step.pose.y) * 20);
    proximity.style.display = index === 2 ? '' : 'none';
    const callout = document.getElementById('story-person-callout');
    callout.replaceChildren();
    if (step.people?.length) {
      const nearest = [...step.people].sort((a, b) => Math.hypot(a.x - step.pose.x, a.y - step.pose.y) - Math.hypot(b.x - step.pose.x, b.y - step.pose.y))[0];
      const x = nearest.x * 20, y = (26 - nearest.y) * 20;
      callout.append(svg('circle', { cx: x, cy: y, r: 5, fill: '#bc6127', stroke: '#fff', 'stroke-width': 2 }));
      callout.append(svg('path', { d: `M${x} ${y} L${x + 24} ${y - 42}`, stroke: '#9b4b24', 'stroke-width': 2, fill: 'none' }));
      const label = svg('text', { x: x + 26, y: y - 44, fill: '#8b3d1b', stroke: '#fff', 'stroke-width': 4, 'paint-order': 'stroke', 'font-family': 'DM Sans, Arial, sans-serif', 'font-size': 14, 'font-weight': 700 });
      label.textContent = 'Person: 0.378 m';
      callout.append(label);
    }
    const previous = document.getElementById('story-previous');
    previous.disabled = index === 0;
    text('story-next', index === 4 ? 'Start again' : `Next: ${recording.steps[index + 1].label}`);
    document.getElementById('story-inspect').open = false;
    centerMap();
  }
  buttons.forEach((button, i) => button.addEventListener('click', () => show(i)));
  document.getElementById('story-previous').addEventListener('click', () => show(index - 1));
  document.getElementById('story-next').addEventListener('click', () => show(index === 4 ? 0 : index + 1));
  host.querySelector('.story-stages').addEventListener('keydown', event => {
    const current = buttons.indexOf(document.activeElement);
    if (current < 0) return;
    const target = event.key === 'ArrowRight' ? (current + 1) % 5
      : event.key === 'ArrowLeft' ? (current + 4) % 5
      : event.key === 'Home' ? 0 : event.key === 'End' ? 4 : null;
    if (target === null) return;
    event.preventDefault();
    show(target);
    buttons[target].focus();
  });
  host.querySelectorAll('[data-story-controls]').forEach(node => { node.hidden = false; });
  window.addEventListener('resize', centerMap);
  show(0);
})();
