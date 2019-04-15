import {
  LitElement,
  html,
  css,
} from "https://unpkg.com/lit-element@2.0.1/lit-element.js?module";


class LoxoneCover extends LitElement {

  static get properties() {
    return {
      name: { type: String },
      hass: Object,
      config: Object,
    }
  }

  constructor() {
    super();
    this.name = "Loxone Cover"
  }

  static get styles() {
    return css`
     .container-1 {
       display:flex;
       align-items:center;
     }
    
    .container-1 div {
      border:0px #ccc solid;
      padding:5px;
    }
  
    .box-1 {
    }

    .box-2 {      
      width:50px;
      flex:1;
    }

    .box-3 {
      padding:0px !important;
    }

    .box-b {
      display:flex;
      flex-direction:column;
    }
    `;
  }

  render() {
    /**
     * `render` must return a lit-html `TemplateResult`.
     *
     * To create 143a `TemplateResult`, tag a JavaScript template literal
     * with the `html` helper function:
     */
    const stateObj = this.hass.states[this.config.entity];

    return html`
      <!-- template content --> 
      <div class="container-1">
      <div class="box-1"><ha-icon icon="mdi:window-closed"></ha-icon></div>
      <div class="box-2">
        <div class=box-b">
          <div>${stateObj.attributes.friendly_name}</div>
          <div>Position: ${stateObj.attributes.current_position_loxone_style} %</div>
        </div> 
      </div>
      <div class="box-3"> 
        <paper-icon-button icon="mdi:view-column" @click="${this._onShade}" ></paper-icon-button>
        <paper-icon-button icon="hass:arrow-up" @click="${this._onUp}" ></paper-icon-button>
        <paper-icon-button icon="hass:stop" @click="${this._onStop}"></paper-icon-button>
        <paper-icon-button icon="hass:arrow-down" @click="${this._onDown}"></paper-icon-button>
      </div>
      </div>
    `;
  }
  _onShade(e) {
    e.stopImmediatePropagation();
    const stateObj = this.hass.states[this.config.entity];
    this.hass.callService("loxone", "event_websocket_command", {
      "uuid": stateObj.attributes.uuid,
      "value": "shade"
    });
  }

  _onUp(e) {
    e.stopImmediatePropagation();
    this.hass.callService("cover", "open_cover", { "entity_id": this.config.entity });
  }
  _onStop(e) {
    e.stopImmediatePropagation();
    this.hass.callService("cover", "stop_cover", { "entity_id": this.config.entity });
  }
  _onDown(e) {
    e.stopImmediatePropagation();
    this.hass.callService("cover", "close_cover", { "entity_id": this.config.entity });
  }

  setConfig(config) {
    if (!config.entity) {
      throw new Error("You need to define entities");
    }
    this.config = config;
    this.name = this.config.entity;
  }

  getCardSize() {
    return 1;
  }

}

// Register the new element with the browser.
customElements.define('loxone-cover', LoxoneCover);
