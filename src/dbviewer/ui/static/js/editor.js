/* Query editor keyboard shortcuts and execution-history interactions. */
window.DBEditor = (() => {
  const el=()=>document.querySelector('#sql-editor');let cm=null;
  function value(){return cm?cm.getValue():el().value;}
  function setValue(text){if(cm)cm.setValue(text);else el().value=text;}
  function selectedSql(){const editor=el();const selection=cm?cm.getSelection():editor.value.slice(editor.selectionStart,editor.selectionEnd);return selection.trim()||value().trim();}
  async function run(){if(!window.DBApp?.state.connection)return;const sql=selectedSql();if(!sql)return;await window.DBApp.runQuery(sql);}
  function init(){if(window.CodeMirror){cm=CodeMirror.fromTextArea(el(),{mode:'text/x-sql',theme:'material-darker',lineNumbers:true,indentWithTabs:false,tabSize:2,viewportMargin:Infinity,extraKeys:{'Ctrl-Enter':run,'Cmd-Enter':run}});}else el().addEventListener('keydown',event=>{if((event.ctrlKey||event.metaKey)&&event.key==='Enter'){event.preventDefault();run();}});document.querySelector('#run-query').addEventListener('click',run);}
  return {init,run,value,setValue};
})();
