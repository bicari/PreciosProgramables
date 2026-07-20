function handleEnterCantidad(event) {
    // 1. Acumular cantidades por código (siempre, no solo en Enter)
    const codigosExistentes = new Map();
    const celdas = document.querySelectorAll('#search-results td[data-codigo]');
    
    celdas.forEach(cell => {
        const codigo = cell.dataset.codigo;
        const valor = parseInt(cell.innerText.trim()) || 0;
        
        if (codigosExistentes.has(codigo)) {
            codigosExistentes.set(codigo, codigosExistentes.get(codigo) + valor);
        } else {
            codigosExistentes.set(codigo, valor);
        }
    });

    // 2. Validar diferencias usando totales acumulados por código único
    const validarTodos = () => {
        codigosExistentes.forEach((valorTotal, codigo) => {
            const codigoNoEncontrado = actualizarEstadoRecepcion(codigo, valorTotal);
            if (codigoNoEncontrado) {
                // Marcar todas las filas del resultado con ese código
                document.querySelectorAll(`#search-results td[data-codigo="${codigo}"]`)
                    .forEach(cell => cell.parentElement.classList.add('table-danger'));
            }
        });
    };

    if (event.key === 'Enter') {
        event.preventDefault();

        // Calcular total general
        let total = 0;
        document.querySelectorAll('#search-results tr').forEach(fila => {
            const cantidadCell = fila.cells[2];
            total += parseFloat(cantidadCell?.textContent.trim()) || 0;
        });
        document.getElementById('band-total').textContent = total.toString();

        const cell = event.target;
        cell.blur();
        
        validarTodos();
    } else {
        validarTodos();
    }
} 
function actualizarEstadoRecepcion(codigo, cantidadRecibida) {
    // Obtener TODAS las filas con ese código en la orden de compra
    const filasOC = document.querySelectorAll(`#search-orden-compra tr[data-codigo="${codigo}"]`);
    if (!filasOC.length) return codigo;

    let restante = cantidadRecibida;

    filasOC.forEach(filaOC => {
        const pendienteCell = filaOC.querySelector('.pendiente');
        const recibidoCell = filaOC.querySelector('.recibido');
        const diferenciaCell = filaOC.querySelector('.diferencia');
        const pendiente = parseInt(pendienteCell.dataset.pendiente);

        // Cuánto absorbe esta fila
        const recibidoEnFila = Math.min(restante, pendiente);
        restante -= recibidoEnFila;  // puede quedar 0 o positivo para la siguiente fila

        const diferencia = recibidoEnFila - pendiente;

        recibidoCell.innerText = recibidoEnFila;
        diferenciaCell.innerText = diferencia;
        diferenciaCell.dataset.diferencia = diferencia;

        filaOC.classList.remove('table-success', 'table-warning', 'table-danger');

        if (diferencia === 0) {
            filaOC.classList.add('table-success');
        } else if (diferencia > 0) {
            filaOC.classList.add('table-warning');
        } else {
            filaOC.classList.add('table-danger');
        }
    });

    // Si sobró cantidad después de llenar todas las filas, marcar la última como warning
    if (restante > 0) {
        const ultimaFila = filasOC[filasOC.length - 1];
        const recibidoCell = ultimaFila.querySelector('.recibido');
        const diferenciaCell = ultimaFila.querySelector('.diferencia');
        const pendienteCell = ultimaFila.querySelector('.pendiente');
        const pendiente = parseInt(pendienteCell.dataset.pendiente);

        recibidoCell.innerText = pendiente + restante;
        diferenciaCell.innerText = restante;
        diferenciaCell.dataset.diferencia = restante;

        ultimaFila.classList.remove('table-success', 'table-danger');
        ultimaFila.classList.add('table-warning');
    }
}

function updateTotal(event) {
    console.log('disparando update total');
    const cantItems = document.getElementById('search-results').rows.length;
    const bandaItems = document.getElementById('band-items');
    bandaItems.textContent = cantItems.toString();

    const button = event.detail.target;
    if (!button) {
        console.warn('No se pudo obtener el botón desde event.detail.elt');
        return;
    }

    const codigo = button.dataset.codigo;

    // Recalcular el acumulado restante en search-results para ese código
    const celdasRestantes = document.querySelectorAll(`#search-results td[data-codigo="${codigo}"]`);
    let totalRestante = 0;
    celdasRestantes.forEach(cell => {
        totalRestante += parseInt(cell.innerText.trim()) || 0;
    });

    // Si no quedan celdas del código, resetear TODAS las filas de la OC con ese código
    const filasOC = document.querySelectorAll(`#search-orden-compra tr[data-codigo="${codigo}"]`);
    if (!filasOC.length) return;

    if (celdasRestantes.length === 0) {
        filasOC.forEach(filaOC => {
            filaOC.classList.remove('table-success', 'table-warning', 'table-danger');
            const recibidoCell = filaOC.querySelector('.recibido');
            const diferenciaCell = filaOC.querySelector('.diferencia');
            if (recibidoCell) recibidoCell.innerText = 0;
            if (diferenciaCell) {
                diferenciaCell.innerText = '';
                diferenciaCell.dataset.diferencia = '';
            }
        });
    } else {
        // Redistribuir el total restante entre todas las filas de la OC
        actualizarEstadoRecepcion(codigo, totalRestante);
    }
}

function postSearchActions(event){
    document.getElementById('search-producto').value = '';
    handleEnterCantidad(event);
    
    
}
    
function addProductModal(event){
  const button = event.currentTarget;
  const filaOriginal = button.closest('tr');
  const tbodyProductos = document.getElementById('search-results');

  // Clona el <tr> completo
  const filaClonada = filaOriginal.cloneNode(true);

  // Elimina la última celda (que contiene el botón original)
  const ultimaCelda = filaClonada.querySelector('td:last-child');
  if (ultimaCelda) filaClonada.removeChild(ultimaCelda);

  // Crea nueva celda con botón de eliminación
  const codigo = filaOriginal.dataset.codigo;
  const tdBoton = document.createElement('td');
  tdBoton.innerHTML = `
    <button type="button" data-codigo="${codigo}" class="btn btn-danger"
            hx-delete="/product-delete/"
            hx-on:htmx:after-request="updateTotal(event)"
            hx-target="closest tr"
            hx-swap="outerHTML">
      <i class="fa-solid fa-trash"></i>
    </button>
  `;
  filaClonada.appendChild(tdBoton);
  console.log(filaClonada);
  // Agrega la fila clonada al tbody
  tbodyProductos.appendChild(filaClonada);
  htmx.process(filaClonada);
  handleEnterCantidad(event);
}

// document.body.addEventListener('htmx:afterSwap', (event) => {
//   console.info('Evento disparado');
//   const tabla = document.getElementById('search-orden-compra');
//   const tablaProductos = document.getElementById('search-results');
//   const totalizar = document.getElementById('totalizar-documento');

//   if (!tabla || !tablaProductos || !totalizar) return;

//   const mostrar = tabla.rows.length > 0 && tablaProductos.rows.length > 0 ;
//   console.info(`Mostrando totalizar: ${mostrar}`);
//   totalizar.classList.toggle('hidden', !mostrar); 

//   const buttonProcesar = document.getElementById('procesar-recepcion');
//   if (buttonProcesar && !buttonProcesar.dataset.listenerAdded) {
//     buttonProcesar.dataset.listenerAdded = 'true';
//     buttonProcesar.addEventListener('click', (event) => {
//       console.log('Procesando recepción de productos...');
//     }, { once: true });
//   }
// });

// document.body.addEventListener('htmx:afterSettle', (event) =>{
//   console.info('Evento outerHTML disparado');const totalizarDocumento = document.getElementById('totalizar-documento');
//   const tabla = document.getElementById('search-orden-compra');
//   const tablaProductos = document.getElementById('search-results');
//   console.info('Antes de validar la vvisilidabb', tablaProductos.rows.length, tabla.rows.length);
//   if ( tablaProductos.rows.length === 0 ||tabla.rows.length === 0 ){
//       console.info('Ocultando totalizar documento');  
//       totalizarDocumento.classList.add('hidden');      
//     }
    
// })

document.body.addEventListener("htmx:error", function (event) {
  
  if ([404, 500, 409].includes(event.detail.errorInfo.xhr.status)) {
    console.info(event.detail)
    const responseText = event.detail.errorInfo.xhr.responseText;
    if (event.detail.elt.id === "search-orden" || event.detail.elt.id ==="search-proveedor"){
        const errorOrden = document.getElementById('error-orden');
        errorOrden.innerHTML = responseText;
        errorOrden.classList.remove('d-none', 'error');
        void errorOrden.offsetWidth;
        errorOrden.classList.add('error');           
      }
    if (event.detail.elt.id === "search-producto"){
        const errorOrden = document.getElementById('error-product');
        errorOrden.innerHTML = responseText;
        errorOrden.classList.remove('d-none', 'error');
        void errorOrden.offsetWidth;
        errorOrden.classList.add('error');
      }      
  }
  
});

document.getElementById("menu-toggle").addEventListener("click", function() {
    const menu = document.querySelector(".nav-side-menu");
    const content = document.querySelector(".main-content");
    const overlay = document.getElementById('sidebar-overlay');

    if (window.innerWidth < 768) {
        // En móvil: toggle como overlay (gestionado desde dashboard.html)
        if (menu.classList.contains('mobile-open')) {
            menu.classList.remove('mobile-open');
            if (overlay) overlay.classList.remove('active');
        } else {
            menu.classList.add('mobile-open');
            if (overlay) overlay.classList.add('active');
        }
    } else {
        const isCollapsed = menu.classList.contains('collapsed');
        const menuList = menu.querySelector('.menu-list');
        // Cerrar submenús abiertos antes de cambiar estado
        menu.querySelectorAll('.menu-toggle').forEach(cb => { cb.checked = false; });
        if (isCollapsed) {
            menu.style.overflow = 'hidden';
            if (menuList) menuList.style.overflow = '';
            menu.classList.remove('collapsed');
            content.classList.remove('expanded');
            setTimeout(() => { menu.style.overflow = ''; }, 310);
        } else {
            menu.style.overflow = 'hidden';
            menu.classList.add('collapsed');
            content.classList.add('expanded');
            // .menu-list tiene overflow-y:auto que también corta el flyout
            setTimeout(() => {
                menu.style.overflow = 'visible';
                if (menuList) menuList.style.overflow = 'visible';
            }, 310);
        }
    }
});
      

document.getElementById("procesar-modal").addEventListener("click", (event)=>{
    const productosOrden = document.querySelectorAll('#search-orden-compra tr');
    const productosRecepcion = document.querySelectorAll('#search-results tr');
    const clasesAfiltrar = ['table-success', 'table-warning', 'table-danger'];
    const filasFiltradas = Array.from(productosOrden).filter(tr =>
    clasesAfiltrar.some(clase => tr.classList.contains(clase))
    
  );
  const productosRecibidos = Array.from(productosRecepcion).map(tr =>
    Array.from(tr.querySelectorAll('td')).map(td => td.textContent.trim())
  );
  const valoresFiltrados = filasFiltradas.map(tr =>
    Array.from(tr.querySelectorAll('td')).map(td => td.textContent.trim())
  );

    console.info(productosOrden.values(), productosRecibidos, filasFiltradas)
  }
)
document.body.addEventListener('htmx:afterRequest', (event) =>{
   //console.info(event.detail.elt?.matches('#search-results'), event.detail.elt)
   if (event.detail.elt?.matches('#search-results')) {
         updateTotal(event);
     }
} );
// document.addEventListener("htmx:afterRequest",(event) => {
//   console.log('Evento disparado escuchado', event.detail)
//   const statusPeticionOrder = event.detail.xhr.status
//   if (statusPeticionOrder === 200){

//   }
// })

function recolectarDatos() {
  const clases = ['table-success', 'table-danger', 'table-warning']
  const ordenes = Array.from(document.querySelectorAll('#search-orden-compra tr'))
  .filter(tr => clases.some(clase => tr.classList.contains(clase)))
  .map(tr => ({
    codigo: tr.cells[0].innerText.trim(),
    orden: tr.cells[1].innerText.trim(),
    cantidad: parseFloat(tr.cells[2].innerText.trim().replace(',', '.')),
    diferencia: parseFloat(tr.cells[3].innerText.trim().replace(',', '.')),
    recibido: parseFloat(tr.cells[5].innerText.trim().replace(',', '.')),
    costo: parseFloat(tr.cells[4].innerText.trim().replace(',', '.')),
    iva: parseInt(tr.cells[6].innerText.trim()),
    moneda: tr.cells[7].innerText.trim(),
    deposito: tr.cells[8].innerText.trim(),
    descripcion: tr.cells[9].innerText.trim(),
    autoincrement: parseInt(tr.cells[10].innerText.trim()),
    puesto: tr.cells[11].innerText.trim(),
    referencia: tr.cells[12].innerText.trim(),
    ref_proveedor: tr.cells[13].innerText.trim(),
    iva_16_monto: parseFloat(tr.cells[14].innerText.trim().replace(',', '.'))
  }));

  const productoSinOc = Array.from(document.querySelectorAll('#search-results tr')).filter(tr => clases.some(clase => tr.classList.contains(clase))).map(tr => ({
    codigo: tr.cells[0].innerText.trim(),
    descripcion: tr.cells[1].innerText.trim(),
    cantidad: parseFloat(tr.cells[2].innerText.trim().replace(',', '.')),
    costoBS: parseFloat(tr.cells[4].innerText.trim().replace(',', '.')),
    costoUS: parseFloat(tr.cells[5].innerText.trim().replace(',', '.')),
    iva: parseInt(tr.cells[6].innerText.trim()),
    puesto: tr.cells[7].innerText.trim()
  }));
  const [rif, proveedor]  =  document.getElementById('card-proveedor').innerText.trim().split('-')
  const comentario = document.getElementById('message-text').value.trim();
  const direccion_proveedor = document.getElementById('direccion-proveedor').innerText.trim();
  const fecha_vencimiento = document.getElementById('fecha-vencimiento').value;
  console.info(ordenes)
  return { ordenes, productoSinOc, proveedor, rif, comentario, direccion_proveedor, fecha_vencimiento};
}
function getCookie(name) {
  let cookieValue = null;
  if (document.cookie && document.cookie !== "") {
    const cookies = document.cookie.split(";");
    for (let i = 0; i < cookies.length; i++) {
      const cookie = cookies[i].trim();
      if (cookie.startsWith(name + "=")) {
        cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
        break;
      }
    }
  }
  return cookieValue;
}

function isPresentTableOc(event){
  const input = event.target
  const ocInput = input.value.trim()
  console.info(input, ocInput)
  
  if (document.querySelector(`#search-orden-compra tr[data-oc="${ocInput}"]`)) {
      event.preventDefault(); // Cancela la petición
      alert(`El documento ${ocInput} ya está en la tabla, por favor seleccione un documento diferente.`);
    }

}

document.getElementById('form-recepcion').addEventListener('submit', function (event) {
  event.preventDefault(); // Prevenir el comportamiento por defecto del formulario
  const botonProcesar = document.getElementById('procesar-modal');
  const datos = recolectarDatos();
  const spinnerButton = document.getElementById('spinner-button');
  spinnerButton.classList.add('spinner-grow', 'spinner-grow-sm')
  console.info(datos)
  botonProcesar.disabled = true;
  fetch('/procesar-recepcion/', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': getCookie('csrftoken') 
      
    },
    body: JSON.stringify(datos)
  })
  .then(response => response.json())
  .then(data => {
    console.log('Respuesta del servidor:', data);
    if (data.status === true){
      spinnerButton.classList.remove('spinner-grow', 'spinner-grow-sm');
      // 1. Convertir Base64 a un Blob de PDF
      const byteCharacters = atob(data.document);
      const byteNumbers = new Array(byteCharacters.length);
      for (let i = 0; i < byteCharacters.length; i++) {
        byteNumbers[i] = byteCharacters.charCodeAt(i);
      }
      const byteArray = new Uint8Array(byteNumbers);
      const blob = new Blob([byteArray], { type: 'application/pdf' });

      // 2. Crear un enlace temporal para la descarga
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = data.filename || 'documento.pdf';
      
      // Añadir al documento, clickear y remover
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);

      // Limpiar la memoria del objeto URL
      window.URL.revokeObjectURL(url);
      setTimeout(() => {
        window.location.href = data.redirect_url;
        botonProcesar.disabled = false;
        }, 1000);
      }
    else{
      spinnerButton.classList.remove('spinner-grow', 'spinner-grow-sm');
      botonProcesar.disabled = false;
      const alertDiv = document.querySelector('.alert-danger');
      alertDiv.classList.remove('d-none');
      if (data.error) {
        alertDiv.innerHTML = data.error;
      } else if (data.errors) {
        const mensajes = Object.entries(data.errors).map(([campo, msgs]) => `${campo}: ${[].concat(msgs).join(', ')}`).join(' | ');
        alertDiv.innerHTML = mensajes;
      } else {
        alertDiv.innerHTML = 'Error al procesar la nota.';
      }

    }
  });
});

function agregarProveedor(event){
  event.preventDefault();
  const fila = event.target.closest('tr')
  const celdas = fila.querySelectorAll('td')
  console.info(celdas);
  const codigo = celdas[0].innerText;
  const descripcion = celdas[1].innerText;
  const direccion = celdas[2].innerText;
  const inputProveedor = document.getElementById('search-proveedor')
  const contenedorProveedor = document.getElementById('card-proveedor')
  console.info(codigo)
  const contenidoHTML = `${codigo.trim()}-${descripcion}<div class="d-none" id="direccion-proveedor">${direccion}</div>`;
  contenedorProveedor.innerHTML = contenidoHTML;
  contenedorProveedor.classList.remove('d-none');
  inputProveedor.value = codigo;
  document.querySelector('#modal-container').innerHTML = '';
  document.getElementById('search-orden').disabled=false; 
  document.getElementById('search-orden').focus()
}

let _preliminarPdfBase64 = null;

const botonProcesar = document.getElementById('procesar-recepcion');

botonProcesar.addEventListener('click', function(event) {
    // Comentario vacío por defecto
    document.getElementById('message-text').value = '';

    // Fecha vencimiento = mañana por defecto
    const manana = new Date();
    manana.setDate(manana.getDate() + 1);
    document.getElementById('fecha-vencimiento').value = manana.toISOString().slice(0, 10);

    // Obtener total_neto y PDF preliminar desde el servidor
    const datos = recolectarDatos();
    fetch('/preliminar-recepcion/', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCookie('csrftoken')
        },
        body: JSON.stringify(datos)
    })
    .then(response => response.json())
    .then(data => {
        if (data.status === true) {
            _preliminarPdfBase64 = data.document;
            const totalFormateado = parseFloat(data.total_neto).toLocaleString('es-VE', {minimumFractionDigits: 2, maximumFractionDigits: 2});
            document.getElementById('total').value = totalFormateado;
        }
    })
    .catch(err => console.error('Error al obtener preliminar:', err));
});

document.getElementById('btn-preliminar').addEventListener('click', function() {
    const base64 = _preliminarPdfBase64;
    if (!base64) {
        alert('Espere a que se cargue el preliminar.');
        return;
    }
    const byteCharacters = atob(base64);
    const byteNumbers = new Array(byteCharacters.length);
    for (let i = 0; i < byteCharacters.length; i++) {
        byteNumbers[i] = byteCharacters.charCodeAt(i);
    }
    const byteArray = new Uint8Array(byteNumbers);
    const blob = new Blob([byteArray], { type: 'application/pdf' });
    const url = URL.createObjectURL(blob);
    window.open(url, '_blank');
});

// ── Prevención global de doble envío ─────────────────────────────────────────
// Bloquea el reenvío por doble clic en todos los formularios que usen el flujo
// nativo (GET/POST). Los formularios que gestionan su propio envío via fetch
// deben marcarse con data-ajax="true" para quedar excluidos.
document.addEventListener('submit', function (e) {
    var form = e.target;
    if (!(form instanceof HTMLFormElement)) return;
    if (form.dataset.ajax === 'true') return;
    if (form.dataset.submitted === 'true') { e.preventDefault(); return; }
    form.dataset.submitted = 'true';
    var btns = form.querySelectorAll('button[type="submit"], input[type="submit"]');
    setTimeout(function () {
        btns.forEach(function (b) { b.disabled = true; });
    }, 0);
});
