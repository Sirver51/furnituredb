let cy = null;
let currentMode = 'semantic';
let currentCenter = null;

function nodeElement(card, isCenter) {
  return {
    data: { id: String(card.id), label: card.name, image: imgUrl(card.image_id) },
    classes: isCenter ? 'center' : '',
  };
}

function initCytoscape() {
  if (cy) cy.destroy();

  cy = cytoscape({
    container: document.getElementById('cy'),
    style: [
      {
        selector: 'node',
        style: {
          'background-image': 'data(image)',
          'background-fit': 'cover',
          'background-color': '#fff',
          label: 'data(label)',
          width: 56,
          height: 56,
          'border-width': 2,
          'border-color': '#9aa5b1',
          'font-size': 8,
          'text-valign': 'bottom',
          'text-margin-y': 6,
          'text-wrap': 'ellipsis',
          'text-max-width': '70px',
        },
      },
      {
        selector: 'node.center',
        style: {
          'border-color': '#e0703a',
          'border-width': 4,
          width: 76,
          height: 76,
        },
      },
      {
        selector: 'edge',
        style: {
          width: 'data(width)',
          'line-color': '#cbd2d9',
          'curve-style': 'bezier',
          label: 'data(label)',
          'font-size': 7,
          color: '#52606d',
          'text-rotation': 'autorotate',
          'text-background-color': '#fff',
          'text-background-opacity': 0.85,
          'text-background-padding': '1px',
          'text-margin-y': -6,
        },
      },
    ],
    layout: { name: 'cose', animate: false },
  });

  cy.on('tap', 'node', (evt) => {
    loadNeighbors(parseInt(evt.target.id(), 10), false);
  });
}

async function loadNeighbors(productId, isCenter) {
  const status = document.getElementById('graph-status');
  status.textContent = 'Loading...';

  const res = await fetch(`/api/product/${productId}/neighbors?mode=${currentMode}&k=10`);
  const data = await res.json();

  if (!data.available || data.center == null) {
    status.textContent = 'No neighbors available for this item/mode (embeddings not indexed yet).';
    if (isCenter) {
      cy.add(nodeElement(data.center || { id: productId, name: '(unknown)', image_id: null }, true));
      cy.layout({ name: 'cose', animate: false }).run();
    }
    return;
  }

  const elements = [];
  if (!cy.getElementById(String(data.center.id)).length) {
    elements.push(nodeElement(data.center, isCenter));
  }
  for (const node of data.nodes) {
    if (!cy.getElementById(String(node.id)).length) {
      elements.push(nodeElement(node, false));
    }
  }
  for (const edge of data.edges) {
    const edgeId = `${edge.source}-${edge.target}`;
    if (!cy.getElementById(edgeId).length) {
      elements.push({
        data: {
          id: edgeId,
          source: String(edge.source),
          target: String(edge.target),
          width: Math.max(1, edge.weight * 6),
          label: edge.similarity != null ? `${edge.similarity}%` : '',
        },
      });
    }
  }

  cy.add(elements);
  cy.layout({ name: 'cose', animate: true, fit: true }).run();
  status.textContent = `${data.nodes.length} neighbors (${currentMode})`;
}

async function openGraph(productId) {
  currentCenter = productId;

  document.getElementById('search-view').classList.add('hidden');
  document.getElementById('detail-view').classList.add('hidden');
  document.getElementById('graph-view').classList.remove('hidden');

  initCytoscape();
  await loadNeighbors(productId, true);
}

document.querySelectorAll('input[name="graph-mode"]').forEach((radio) => {
  radio.addEventListener('change', async (e) => {
    currentMode = e.target.value;
    if (currentCenter != null) {
      initCytoscape();
      await loadNeighbors(currentCenter, true);
    }
  });
});
